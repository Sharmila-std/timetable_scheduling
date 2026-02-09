import networkx as nx
import random
from collections import defaultdict
import copy
from bson import ObjectId

# ---------------- CONFIG ----------------
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SLOTS = list(range(1, 9))   # slot 9 blocked
FN_SLOTS = {1, 2, 3, 4}
AN_SLOTS = {5, 6, 7, 8}

def run_custom_ga(db, batch_ids, log_callback=None):
    """
    Executes the Custom Genetic Algorithm for the given batches.
    Yields ("LOG", message) or ("RESULT", (timetables, fitness_curve))
    """
    # Helper to yield log and optionally call callback (for backward compat if needed)
    def log(msg):
        pass # We will yield directly, but keep this for internal logic if needed
    
    yield ("LOG", f"Starting Custom GA for {len(batch_ids)} batches...")

    # ---------------- 1 DATA FETCHING ----------------
    batches = list(db.batches.find({'_id': {'$in': [ObjectId(bid) for bid in batch_ids]}}))
    all_rooms = list(db.rooms.find())
    all_faculty = list(db.faculty.find())
    
    # ---------------- 1b. FETCH EXISTING TIMETABLES (Incremental Scheduling) ----------------
    # Find timetables for batches NOT in the current generation list
    # This ensures we respect previously generated schedules
    current_batch_ids = [ObjectId(bid) for bid in batch_ids]
    existing_timetables = list(db.timetables.find({'batch_id': {'$nin': current_batch_ids}}))
    
    occupied_faculty = defaultdict(lambda: defaultdict(set)) # faculty -> day -> set(slots)
    occupied_rooms = defaultdict(lambda: defaultdict(set))   # room -> day -> set(slots)
    
    for tt in existing_timetables:
        t_data = tt.get('timetable', {})
        for day, slots in t_data.items():
            for slot_num, details in slots.items():
                if not details: continue
                s_int = int(slot_num)
                
                # Mark Faculty Busy
                if 'faculty_name' in details:
                    occupied_faculty[details['faculty_name']][day].add(s_int)
                    
                # Mark Room Busy
                if 'room' in details and details['room'] != 'TBD':
                     occupied_rooms[details['room']][day].add(s_int)
                     
    yield ("LOG", f"Found {len(existing_timetables)} existing timetables to respect.")
    
    # Pre-fetch courses and labs to avoid N+1 queries
    course_ids = set()
    lab_ids = set()
    for b in batches:
        course_ids.update([ObjectId(c) for c in b.get('courses', [])])
        lab_ids.update([ObjectId(l) for l in b.get('labs', [])])
    
    courses_map = {str(c['_id']): c for c in db.courses.find({'_id': {'$in': list(course_ids)}})}
    labs_map = {str(l['_id']): l for l in db.labs.find({'_id': {'$in': list(lab_ids)}})}

    # ---------------- DYNAMIC MAPPING ----------------
    
    # 1. BATCHES
    BATCH_NAMES = [b['name'] for b in batches]
    
    # 2. ROOMS (Simple allocation strategy: Round-robin assign Lecture Halls to Batches)
    lecture_halls = [r['number'] for r in all_rooms if r.get('type') == 'Lecture Hall']
    LAB_ROOMS = [r['number'] for r in all_rooms if r.get('type') == 'Lab']
    
    BATCH_ROOMS = {}
    for i, batch in enumerate(batches):
        b_id_str = str(batch['_id'])
        if lecture_halls:
            BATCH_ROOMS[b_id_str] = lecture_halls[i % len(lecture_halls)]
        else:
            BATCH_ROOMS[b_id_str] = "TBD"

    yield ("LOG", f"Room Allocation: {BATCH_ROOMS}")
    yield ("LOG", f"Available Labs: {LAB_ROOMS}")

    # 3. FACULTY MAPPING
    # Map DB Faculty to the structure: name -> {off, max_day}
    faculty_config = {}
    for f in all_faculty:
        # Check if they have availability constraints
        constraint = db.constraints.find_one({"rule": "TEACHER_AVAILABILITY", "entity_id": str(f['_id'])})
        off_day = None
        # Simplified: If they have ANY unavailable slot on a day, we might mark that day as 'off' strictly 
        # OR better: The original code supports 'off' as a full day. 
        # Let's see if we can derive a 'max_day' constraint or just use default.
        limit = 4 # Default max slots per day
        faculty_config[f['name']] = {"off": off_day, "max_day": limit}

    # 4. SEMESTER PLAN CONSTRUCTION
    semester_plan = {}
    
    for batch in batches:
        plan = []
        b_name = batch['name']
        
        # Theory Courses
        for c_id in batch.get('courses', []):
            c_str = str(c_id)
            if c_str not in courses_map: continue
            course = courses_map[c_str]
            
            # Find a qualified faculty
            qualified_faculty = []
            for f in all_faculty:
                if c_str in f.get('qualified_courses', []):
                    qualified_faculty.append(f['name'])
            
            assigned_faculty = random.choice(qualified_faculty) if qualified_faculty else "Staff"
            
            pref_session = course.get('preferred_session') # 'FN', 'AN', or None/Empty
            
            plan.append({
                "code": course['code'],
                "name": course['name'], # Added Name
                "credits": int(course.get('credits', 4)),
                "faculty": assigned_faculty,
                "type": "theory",
                "pref_session": pref_session
            })
            
        # Labs
        for l_id in batch.get('labs', []):
            l_str = str(l_id)
            if l_str not in labs_map: continue
            lab = labs_map[l_str]
            
            qualified_faculty = []
            for f in all_faculty:
                if l_str in f.get('qualified_labs', []):
                    qualified_faculty.append(f['name'])
            
            assigned_faculty = random.choice(qualified_faculty) if qualified_faculty else "Staff"
            
            plan.append({
                "code": lab['code'],
                "name": lab['name'], # Added Name
                "credits": 2, # Labs usually 2 slots
                "faculty": assigned_faculty,
                "type": "lab",
                "type": "lab",
                "pref_session": None # Labs mostly flexible or handled by room, but could add if needed
            })
            
            
        semester_plan[str(batch['_id'])] = plan

    # ---------------- STEP 1: CREATE SESSIONS ----------------
    yield ("LOG", "Creating sessions...")
    sessions = []
    for batch in batches:
        b_id = str(batch['_id'])
        b_name = batch['name']
        if b_id not in semester_plan:
            continue
        for c in semester_plan[b_id]:
            if c["type"] == "theory":
                for i in range(c["credits"]):
                    sessions.append({
                        "id": f"{b_id}_{c['code']}_{i}",
                        "batch_id": b_id,
                        "batch": b_name,
                        "course": c["code"],
                        "course_name": c["name"],
                        "faculty": c["faculty"],
                        "type": "theory",
                        "pref_session": c["pref_session"]
                    })
            else:
                sessions.append({
                    "id": f"{b_id}_{c['code']}_LAB",
                    "batch_id": b_id,
                    "batch": b_name,
                    "course": c["code"],
                    "course_name": c["name"],
                    "faculty": c["faculty"],
                    "type": "lab",
                    "pref_session": c["pref_session"]
                })

    yield ("LOG", f"Total Sessions: {len(sessions)}")

    # ---------------- STEP 2: CONFLICT GRAPH ----------------
    G = nx.Graph()
    for s in sessions:
        G.add_node(s["id"], data=s)

    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            a, b = sessions[i], sessions[j]
            if a["batch_id"] == b["batch_id"] or a["faculty"] == b["faculty"]:
                G.add_edge(a["id"], b["id"])

    # ---------------- STEP 3: INITIAL ASSIGNMENT (DSATUR) ----------------
    yield ("LOG", "Running DSATUR Initialization...")
    TIME_SLOTS = [(d, s) for d in DAYS for s in SLOTS]
    domain = {}
    
    for s in sessions:
        allowed = []
        for d, sl in TIME_SLOTS:
            # 0. Check GLOBAL Occupation (Incremental)
            if sl in occupied_faculty[s["faculty"]][d]:
                continue
            
            # Check occupied room if known (Theory only usually)
            if s["type"] != "lab":
                 # We don't know the exact room at this stage for theory unless pre-assigned
                 # But if we did, we'd check `occupied_rooms`
                 pass

            fac_data = faculty_config.get(s["faculty"], {"off": None, "max_day": 4})
            if fac_data["off"] and d == fac_data["off"]:
                continue
            # if s["pref_session"] == 'FN' and sl not in FN_SLOTS: continue (Softened)
            # if s["pref_session"] == 'AN' and sl not in AN_SLOTS: continue (Softened)
            if s["type"] == "lab" and sl >= 8: # Lab needs 2 slots, can't start at 8
                continue
            allowed.append((d, sl))
        domain[s["id"]] = allowed

    faculty_load = defaultdict(lambda: defaultdict(int))
    room_usage = defaultdict(lambda: defaultdict(set)) 
    lab_usage_count = defaultdict(lambda: defaultdict(int))
    faculty_slots = defaultdict(lambda: defaultdict(set)) # Track slots for consecutive constraint
    assignment = {}

    try:
        # Fallback if graph is empty
        if not G.nodes():
            nodes_to_color = []
        else:
            nodes_to_color = nx.coloring.greedy_color(G, strategy="DSATUR")
    except Exception as e:
        yield ("LOG", f"DSATUR Error: {e}, falling back to list")
        nodes_to_color = list(G.nodes())

    for node in nodes_to_color:
        s = G.nodes[node]["data"]
        possible_slots = domain.get(node, TIME_SLOTS)
        random.shuffle(possible_slots)

        if s["type"] != "lab":
            required_room = BATCH_ROOMS.get(s["batch_id"], "Unknown")
        else:
            required_room = None 

        for (day, slot) in possible_slots:
            fac = s["faculty"]
            needed = 2 if s["type"] == "lab" else 1
            
            # 1. Faculty Load
            if faculty_load[fac][day] + needed > faculty_config.get(fac, {"max_day":4})["max_day"]:
                continue

            # 2. Room/Resource Check
            if s["type"] != "lab":
                if required_room and required_room in room_usage[day][slot]:
                    continue
            else:
                # Lab Pool Check
                if len(LAB_ROOMS) > 0:
                    if lab_usage_count[day][slot] >= len(LAB_ROOMS): continue
                    if lab_usage_count[day][slot+1] >= len(LAB_ROOMS): continue

            # 3. Graph Conflicts
            conflict = False
            for neigh in G.neighbors(node):
                if neigh in assignment:
                    n_day, n_slot = assignment[neigh]
                    if n_day == day and n_slot == slot:
                        conflict = True; break
                    if s['type'] == 'lab' and n_day == day and n_slot == slot + 1:
                        conflict = True; break
                    if G.nodes[neigh]["data"]['type'] == 'lab' and n_day == day and n_slot + 1 == slot:
                        conflict = True; break
            
            if conflict:
                continue

            # 4. Consecutive Slot Constraint Check
            # Temporarily add slots to see if it violates limit
            temp_slots = sorted(list(faculty_slots[fac][day] | {slot} | ({slot+1} if s["type"]=="lab" else set())))
            consecutive = 0
            last_sl = -1
            too_many = False
            for sl_chk in temp_slots:
                 if sl_chk == last_sl + 1:
                     consecutive += 1
                 else:
                     consecutive = 1
                 last_sl = sl_chk
                 if consecutive > 2:
                     too_many = True; break
            
            if too_many:
                continue

            # Assign
            assignment[node] = (day, slot)
            faculty_load[fac][day] += needed
            faculty_slots[fac][day].add(slot)
            if s["type"] == "lab":
                faculty_slots[fac][day].add(slot + 1)
            
            if s["type"] != "lab":
                room_usage[day][slot].add(required_room)
            else:
                lab_usage_count[day][slot] += 1
                lab_usage_count[day][slot+1] += 1
                
            break
            
        if node not in assignment:
            # Force random assignment if no legal slot (Soft fail)
            if possible_slots:
                assignment[node] = random.choice(possible_slots)

    # ---------------- STEP 4 & 5: FITNESS & HARD CONSTRAINTS ----------------
    
    def hard_ok(assign):
        f_load = defaultdict(lambda: defaultdict(int))
        r_usage = defaultdict(lambda: defaultdict(set))
        l_usage = defaultdict(lambda: defaultdict(int)) 
        
        # Structure to track slots for consecutive check: faculty -> day -> set(slots)
        f_slots = defaultdict(lambda: defaultdict(set))

        for node, (d, sl) in assign.items():
            s = G.nodes[node]["data"]
            fac = s["faculty"]
            needed = 2 if s["type"] == "lab" else 1
            
            f_load[fac][d] += needed
            if f_load[fac][d] > faculty_config.get(fac, {"max_day":4})["max_day"]:
                return False
                
            # Check Global Faculty Conflict (Incremental)
            if sl in occupied_faculty[fac][d]: return False
            if s["type"] == "lab":
                if (sl+1) in occupied_faculty[fac][d]: return False
            
            # Track slots for consecutive check
            f_slots[fac][d].add(sl)
            if s["type"] == "lab":
                f_slots[fac][d].add(sl + 1)
            
            if s["type"] == "lab":
                 if len(LAB_ROOMS) > 0:
                     if l_usage[d][sl] >= len(LAB_ROOMS): return False
                     l_usage[d][sl] += 1
                     if l_usage[d][sl+1] >= len(LAB_ROOMS): return False
                     l_usage[d][sl+1] += 1
            else:
                room = BATCH_ROOMS.get(s["batch_id"], "Unknown")
                
                # Check Global Room Conflict (Incremental)
                if sl in occupied_rooms[room][d]: return False
                
                if room in r_usage[d][sl]: return False
                r_usage[d][sl].add(room)
                
            for neigh in G.neighbors(node):
                if neigh in assign:
                    n_day, n_slot = assign[neigh]
                    if n_day == d and n_slot == sl: return False
                    if s["type"] == "lab" and n_day == d and n_slot == sl+1: return False
                    if G.nodes[neigh]["data"]["type"] == "lab" and n_day == d and n_slot+1 == sl: return False

        # Check Consecutive Slots
        for fac in f_slots:
            for d in f_slots[fac]:
                slots = sorted(list(f_slots[fac][d]))
                consecutive = 0
                last_slot = -1
                for sl in slots:
                    if sl == last_slot + 1:
                        consecutive += 1
                    else:
                        consecutive = 1
                    last_slot = sl
                    
                    if consecutive > 2:
                        return False

        return True

    def fitness(assign):
        score = 0
        tt = defaultdict(lambda: defaultdict(list))
        tt_details = defaultdict(lambda: defaultdict(list))

        for node, (d, sl) in assign.items():
            s = G.nodes[node]["data"]
            tt[s["batch_id"]][d].append(sl)
            tt_details[s["batch_id"]][d].append(s)
            if s["type"] == "lab":
                tt[s["batch_id"]][d].append(sl+1)
            
            # --- SOFT CONSTRAINT: Session Preference ---
            # Penalty for violation, allowing flexibility for hard constraints
            if s.get("pref_session") == 'FN' and sl not in FN_SLOTS:
                score -= 20 # Penalty
            elif s.get("pref_session") == 'AN' and sl not in AN_SLOTS:
                score -= 20 # Penalty
                
        for batch in batches:
            b_id = str(batch['_id'])
            for d in DAYS:
                slots = sorted(tt[b_id][d])
                details = tt_details[b_id][d]
                
                if not slots:
                    score -= 15  
                else:
                    gaps = (slots[-1] - slots[0] + 1) - len(slots)
                    score -= gaps * 5
                    
                    if len(slots) > 5:
                        score -= (len(slots) - 5) * 10

                    avg_slots = sum(len(tt[b_id][dx]) for dx in DAYS if tt[b_id][dx]) / 5
                    score -= abs(len(slots) - avg_slots) * 2

                day_map = {}
                for node, (day_a, slot_a) in assign.items():
                     if G.nodes[node]["data"]["batch_id"] == b_id and day_a == d:
                         day_map[slot_a] = G.nodes[node]["data"]["type"]
                
                for sl in slots:
                    if sl > 4 and day_map.get(sl) == "theory":
                        score -= 2 
                
                lab_count = sum(1 for s in details if s["type"] == "lab")
                if lab_count > 1:
                    score -= 20
        
        return score

    # ---------------- STEP 6: GA OPTIMIZATION ----------------
    yield ("LOG", "Running Genetic Algorithm Loop...")
    best_assignment = assignment
    best_score = fitness(best_assignment)
    yield ("LOG", f"Initial Fitness: {best_score}")
    
    fitness_curve = [best_score]

    ITERATIONS = 1000 # Tuned down slightly for web response
    
    for i in range(ITERATIONS):
        if not best_assignment: break # Safety
        
        candidate = copy.deepcopy(best_assignment)
        
        node = random.choice(list(candidate.keys()))
        s = G.nodes[node]["data"]
        d = random.choice(DAYS)
        
        if s["pref_session"] == 'FN':
            sl = random.choice(list(FN_SLOTS))
        elif s["pref_session"] == 'AN':
            sl = random.choice(list(AN_SLOTS))
        else:
            sl = random.choice(SLOTS)
        
        # Constraints check for mutation
        # if s["pref_session"] == 'FN' and sl not in FN_SLOTS: continue (Softened)
        # if s["pref_session"] == 'AN' and sl not in AN_SLOTS: continue (Softened)
        if s["type"] == "lab" and sl >= 8: continue
        
        # Mutation: Respect Global Conflicts
        if sl in occupied_faculty[s["faculty"]][d]: continue
        if s["type"] == "lab" and (sl+1) in occupied_faculty[s["faculty"]][d]: continue
        
        if s["type"] != "lab":
             room = BATCH_ROOMS.get(s["batch_id"], "Unknown")
             if sl in occupied_rooms[room][d]: continue
        
        candidate[node] = (d, sl)
        
        if hard_ok(candidate):
            score = fitness(candidate)
            if score > best_score:
                best_score = score
                best_assignment = candidate
                yield ("LOG", f"Iter {i}: New Best Score {best_score}")
        
        # Heartbeat to keep connection alive
        if i % 50 == 0:
            yield ("LOG", f"STATUS:WORKING:ITER:{i}")
            fitness_curve.append(best_score)
            
    yield ("LOG", f"Final Fitness: {best_score}")

    # ---------------- FORMAT OUTPUT ----------------
    # Convert to schema: { batch_id: { day: { slot: "course" } } }
    
    # 1. Map Back ID to Object - NO LONGER NEEDED due to ID refactor
    # batch_name_to_id = {b['name']: b['_id'] for b in batches}
    
    yield ("LOG", "Formatting Output...")
    final_timetables = {}
    
    # Initialize empty structures
    for b in batches:
        final_timetables[b['_id']] = {d: {} for d in DAYS}

    # Populate
    for node, (day, slot) in best_assignment.items():
        s = G.nodes[node]["data"]
        b_id = ObjectId(s["batch_id"])
        
        # Room assignment
        room = BATCH_ROOMS.get(s["batch_id"], "TBD")
        
        # entry_text = f"{s['course']} ({s['faculty']}) [{room}]"
        
        # Create object structure for Template
        slot_data = {
            'code': s['course'],
            'name': s['course_name'], # Added to output
            'faculty_name': s['faculty'],
            'room': room,
            'type': 'Theory' if s['type'] != 'lab' else 'LAB'
        }
        
        final_timetables[b_id][day][str(slot)] = slot_data
        
        if s["type"] == "lab":
             # Use same object or similar for reference, but type is LAB
             lab_slot_data = slot_data.copy()
             lab_slot_data['type'] = 'LAB'
             final_timetables[b_id][day][str(slot+1)] = lab_slot_data
             
    yield ("RESULT", (final_timetables, fitness_curve))
