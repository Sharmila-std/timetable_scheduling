from bson import ObjectId
import random
from collections import defaultdict

class MultiBatchScheduler:
    def __init__(self, db, batch_ids):
        self.db = db
        self.batch_ids = [ObjectId(bid) for bid in batch_ids]
        self.days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        self.slots = [str(i) for i in range(1, 10)]
        self.debug_logs = []
        
        # Global State
        self.availability_matrix = defaultdict(dict) # key=entity_id (fac/room), val={day_slot: True}
        self.daily_load = defaultdict(lambda: defaultdict(int)) # key=fac_id, val={day: count}
        self.timetables = {} # key=batch_id, val={day: {slot: entry}}
        self.course_day_usage = defaultdict(lambda: defaultdict(set)) # batch_id -> course_code -> set(days)
        
        # Hard Constraints Configurations
        # We model breaks as boundaries. If a 2-hr block crosses a boundary, it's invalid.
        # Break after Slot 2. Lunch after Slot 5.
        self.break_boundaries = {2, 5} 

    def violates_continuous_teaching(self, faculty_id, day, req_slots):
        """
        Ensures faculty does NOT teach more than 2 continuous slots.
        """
        occupied = set()

        # Collect already occupied slots for faculty on this day
        # From Global Availability
        # Keys are "Mon_1", "Mon_2" etc
        prefix = f"{day}_"
        for key in self.availability_matrix.get(faculty_id, {}):
            if key.startswith(prefix):
                slot_num = int(key.split('_')[1])
                occupied.add(slot_num)

        # Include proposed slots
        proposed = [int(s) for s in req_slots]
        all_slots = sorted(occupied.union(proposed))

        # Check for continuous runs > 2
        streak = 1
        for i in range(1, len(all_slots)):
            if all_slots[i] == all_slots[i-1] + 1:
                streak += 1
                if streak > 2:
                    return True
            else:
                streak = 1

        return False
        
    def log(self, msg):
        self.debug_logs.append(msg)

    def load_data(self):
        self.batches = list(self.db.batches.find({'_id': {'$in': self.batch_ids}}))
        self.all_faculty = list(self.db.faculty.find())
        self.all_rooms = list(self.db.rooms.find())
        
        # Load Existing Constraints (Faculty Unavailability)
        constraints = list(self.db.constraints.find({'rule': 'TEACHER_AVAILABILITY'}))
        for c in constraints:
            fid = str(c['entity_id'])
            for slot_str in c['data']['unavailable_slots']: # e.g. "Mon_1"
                self.availability_matrix[fid][slot_str] = True 
                
        # Load Global Busy State (from OTHER timetables not in this run)
        other_tts = list(self.db.timetables.find({'batch_id': {'$nin': self.batch_ids}}))
        for tt in other_tts:
            t_data = tt.get('timetable', {})
            for day in self.days:
                for slot in self.slots:
                    entry = t_data.get(day, {}).get(slot)
                    if entry:
                        key_suffix = f"{day}_{slot}"
                        if 'faculty_id' in entry:
                            self.availability_matrix[entry['faculty_id']][key_suffix] = True
                        if 'room_id' in entry:
                            self.availability_matrix[entry['room_id']][key_suffix] = True
                            
    def initialize_structure(self):
        for b in self.batches:
            self.timetables[b['_id']] = {day: {slot: None for slot in self.slots} for day in self.days}

    def expand_sessions(self):
        """Convert courses/labs into schedulable session objects."""
        sessions = []
        for batch in self.batches:
            # Labs
            labs = list(self.db.labs.find({'_id': {'$in': [ObjectId(l) for l in batch['labs']]}}))
            for lab in labs:
                sessions.append({
                    'type': 'LAB',
                    'batch_id': batch['_id'],
                    'batch_name': batch['name'],
                    'course': lab,
                    'duration': 2,
                    'valid_slots': [(6,7), (7,8), (8,9)], # Avoid (5,6) crossing lunch if Lunch is after 5
                    'faculty_pool': self.get_qualified_faculty(lab, 'qualified_labs'),
                    'room_pool': [r for r in self.all_rooms if r['type'] == 'Laboratory']
                })
            
            # Theory
            courses = list(self.db.courses.find({'_id': {'$in': [ObjectId(c) for c in batch['courses']]}}))
            for course in courses:
                # DEFENSIVE: Skip if it looks like a lab (e.g. 1 credit, name contains Lab, or in labs collection)
                # Ideally, rely on DB, but 'credits' is a good proxy if labs are 1 and theory > 1
                # Or check if code exists in labs collection? 
                # For now, trust DB but add explicit type if missing.
                
                credits = int(course.get('credits', 3))
                pref = course.get('preferred_session', 'Any')
                
                # Valid Slots
                if pref == 'FN': v_slots = [1, 2, 3, 4]
                elif pref == 'AN': v_slots = [5, 6, 7, 8, 9]
                else: v_slots = [1, 2, 3, 4, 5, 6, 7, 8, 9]
                
                for _ in range(credits):
                    sessions.append({
                        'type': 'THEORY',
                        'batch_id': batch['_id'],
                        'batch_name': batch['name'],
                        'course': course,
                        'duration': 1,
                        'valid_slots': v_slots, # List of single slots
                        'faculty_pool': self.get_qualified_faculty(course, 'qualified_courses'),
                        'room_pool': [r for r in self.all_rooms if r['type'] == 'Lecture Hall']
                    })
        
        # Sort sessions: Labs first (Hardest), then Theory
        sessions.sort(key=lambda x: 0 if x['type'] == 'LAB' else 1)
        return sessions

    def get_qualified_faculty(self, subject, field):
        return [f for f in self.all_faculty if field in f and str(subject['_id']) in f[field]]

    def is_slot_available(self, resource_id, day, slot_list):
        """Check if resource is available for ALL slots in the list."""
        for s in slot_list:
            if self.availability_matrix.get(resource_id, {}).get(f"{day}_{s}"):
                return False
        return True

    def allocate(self, strict_mode=True):
        # Use the instance flag if it's been set, otherwise use the parameter default
        current_strict_mode = self.strict_mode_flag if hasattr(self, 'strict_mode_flag') else strict_mode

        self.load_data()
        self.initialize_structure()
        sessions = self.expand_sessions()
        
        # 1. OPTIMIZE ORDERING WITH DSATUR
        try:
            from services.dsatur import build_conflict_graph, dsatur_coloring
            graph = build_conflict_graph(sessions)
            coloring = dsatur_coloring(graph, len(sessions))
            for idx, sess in enumerate(sessions):
                sess['dsatur_color'] = coloring.get(idx, 999)
        except Exception as e:
            self.log(f"DSATUR Failed: {e}")
            
        # Sort: Hardest First (Labs), then by Color, then Duration
        # If strict_mode is False, maybe just random? No, sorted is always better.
        sessions.sort(key=lambda x: (0 if x['type'] == 'LAB' else 1, x.get('dsatur_color', 999), -x['duration']))
        
        unallocated = []
        
        for sess in sessions:
            assigned = False
            
            shuffled_days = self.days[:]
            # If strict, maybe don't shuffle to preserve ordering? 
            # But we need distribution. Random is fine.
            random.shuffle(shuffled_days)
            
            for day in shuffled_days:
                if assigned: break
                
                # Determine slot candidates
                candidates = sess['valid_slots'][:] 
                random.shuffle(candidates)
                
                for start_slot in candidates:
                    if isinstance(start_slot, tuple):
                        req_slots = [str(s) for s in start_slot]
                    else:
                        req_slots = [str(start_slot)]
                    
                    # 1. Check Batch Availability
                    if not self.is_clean_batch_slot_v2(sess['batch_id'], day, req_slots, sess):
                        continue
                     
                    # 1.5 Compactness Check (SKIP IF RELAXED)
                    if current_strict_mode and self.batch_has_large_gap(sess['batch_id'], day, req_slots):
                        continue   
                    
                    # 2. Find Faculty
                    chosen_fac = None
                    fac_pool = sess['faculty_pool'][:]
                    random.shuffle(fac_pool)

                    for fac in fac_pool:
                        fid = str(fac['_id'])
                        
                        if not self.is_slot_available(fid, day, req_slots): 
                            continue
                        
                        # Max Load (Hard logic, but maybe relax max load to 5 in non-strict?)
                        # Let's keep 4 hard for now, unless fallback needed.
                        limit = 4 if current_strict_mode else 5
                        if self.daily_load[fid][day] + sess['duration'] > limit: 
                            continue 
                        
                        # Continuous Teaching (SKIP IF RELAXED)
                        if current_strict_mode and self.violates_continuous_teaching(fid, day, req_slots): 
                            continue
                        
                        chosen_fac = fac
                        break
                    
                    if not chosen_fac: 
                        continue
                    
                    # 3. Find Room
                    chosen_room = None
                    room_pool = sess['room_pool'][:]
                    random.shuffle(room_pool)
                    
                    for room in room_pool:
                        rid = str(room['_id'])
                        if self.is_slot_available(rid, day, req_slots):
                            chosen_room = room
                            break
                            
                    if chosen_fac and chosen_room:
                        # ALLOCATE
                        self.register_allocation(sess, day, req_slots, chosen_fac, chosen_room)
                        assigned = True
                        break
            
            if not assigned:
                unallocated.append(sess)
                self.log(f"FAILED to allocate {sess['course']['code']}")
                # print(f"DEBUG: Failed {sess['course']['code']} Batch {sess['batch_name']}. ValidSlots: {len(sess['valid_slots'])}") # Removed as per instruction

        return self.timetables, unallocated

    def is_clean_batch_slot(self, batch_id, day, req_slots):
        tt = self.timetables[batch_id][day]
        for s in req_slots:
            if tt.get(s): return False 
        
        # Additional Constraint: 1 Slot/Day for same Theory course
        # We need the course code from current session context, but it's not passed here.
        # Let's updated calls to pass session info or handle it here.
        # BETTER: Pass 'session' to this function.
        return False

    def batch_has_large_gap(self, batch_id, day, req_slots):
        """Avoids creating gaps > 2 slots."""
        tt = self.timetables[batch_id][day]
        occupied = sorted([int(s) for s,v in tt.items() if v])
        
        if not occupied: return False # First slot is always fine

        # Add proposed
        for s in req_slots: occupied.append(int(s))
        occupied.sort()

        # Check gaps
        for i in range(1, len(occupied)):
            if occupied[i] - occupied[i-1] > 2: # strict gap > 1? User said > 2 is ugly.
                # Allow gap of 1 (Reasonable break), Gap of 2 is pushing it.
                return True
        return False

    def is_clean_batch_slot_v2(self, batch_id, day, req_slots, session):
        tt = self.timetables[batch_id][day]
        
        # 1. Slot must be empty
        for s in req_slots:
            if tt.get(s): return False
            
        # 2. Same Theory Course only once per day (Using tracked set)
        if session['type'] == 'THEORY':
             used_days = self.course_day_usage[batch_id][session['course']['code']]
             if day in used_days:
                 return False
                     
        return True

    def register_allocation(self, session, day, slots, faculty, room):
        fid = str(faculty['_id'])
        rid = str(room['_id'])
        
        entry = {
            "type": session['type'],
            "name": session['course']['name'],
            "code": session['course']['code'],
            "faculty_name": faculty['name'],
            "faculty_id": fid,
            "room": room['number'],
            "room_id": rid
        }
        
        for s in slots:
            # 1. Update Batch Timetable
            self.timetables[session['batch_id']][day][s] = entry
            
            # 2. Update Global Availability Matrix
            key_suffix = f"{day}_{s}"
            self.availability_matrix[fid][key_suffix] = True
            self.availability_matrix[rid][key_suffix] = True
            
        # 3. Update Load
        self.daily_load[fid][day] += session['duration']
        
        # 4. Update Course Usage
        if session['type'] == 'THEORY':
            self.course_day_usage[session['batch_id']][session['course']['code']].add(day)

    def validate_final_timetable(self):
        """Final sanity check before commit."""
        errors = []
        for fid, daily in self.daily_load.items():
            for day, load in daily.items():
                if load > 4:
                    errors.append(f"Faculty {fid} Overload on {day}: {load} hours")
        
        # Check continuity, room conflicts etc if needed explicitly
        return errors

# Wrapper function to be called by optimization engine
def create_unified_timetable(batch_ids, db, min_fitness=0):
    from services.ga_optimizer import GeneticOptimizer
    import traceback
    
    best_overall = None
    best_score = float('-inf')
    best_curve = []

    # Retry loop (Outer quality assurance)
    max_retries = 3
    for attempt in range(max_retries):
        print(f"DEBUG: Optimization Attempt {attempt+1}/{max_retries}")
        
        try:
            # New Scheduler Instance per attempt
            scheduler = MultiBatchScheduler(db, batch_ids)
            ga = GeneticOptimizer(scheduler, generations=5) # Short generations for speed in demo
            
            tt, curve = ga.run(log_fn=lambda m: scheduler.log(m))
            
            # Check if empty solution returned
            if not curve:
                print("DEBUG: GA returned no curve/result.")
                continue
                
            score = curve[-1]
            print(f"DEBUG: Attempt {attempt+1} Score: {score}")

            if score > best_score:
                best_score = score
                best_overall = tt
                best_curve = curve

            # Threshold check (tuning required to know what's 'good')
            if score >= min_fitness and min_fitness > 0:
                break
        except Exception as e:
            print(f"DEBUG: EXCEPTION in Optimization Attempt: {e}")
            traceback.print_exc()

    return best_overall, best_curve

# Backwards compatibility wrapper for single-batch route
def create_timetable(batch_id, db):
    results, _ = create_unified_timetable([batch_id], db)
    return results.get(ObjectId(batch_id))
