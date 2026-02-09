from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId
import random

client = MongoClient("mongodb+srv://sharmila:123456_sharmila@capstone.3xycmpu.mongodb.net/?appName=capstone")
db = client['se_tt']
db_leaves = client['timetable_db']

def generate_substitution_plan(leave_id):
    leave_id = leave_id.strip()
    try:
        oid = ObjectId(leave_id)
    except:
        print(f"DEBUG: Invalid ObjectId format: '{leave_id}'")
        return None
        
    leave_req = db_leaves.leave_requests.find_one({'_id': oid})
    if not leave_req: 
        print(f"DEBUG: Leave Request {leave_id} not found")
        return None
    
    faculty_name = leave_req['faculty_name']
    start_date_str = leave_req['start_date']
    end_date_str = leave_req['end_date']
    
    # 1. Determine Affected Days
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except ValueError:
        print(f"DEBUG: Date parsing error for {start_date_str} - {end_date_str}")
        return None

    affected_day_names = set()
    current_date = start_date
    while current_date <= end_date:
        affected_day_names.add(current_date.strftime("%a"))
        current_date += timedelta(days=1)
        
    print(f"DEBUG: Processing Substitution for {faculty_name} on days {affected_day_names}")

    # 2. Identify all Classes taught by this faculty on those days
    all_timetables = list(db.timetables.find())
    affected_slots = [] 
    
    # Build Global Occupancy Map & Batch-Faculty Map
    global_busy_map = set() # (Faculty, Day, Slot) -> True
    faculty_slots = {} # (Faculty) -> LIST of (Day, Slot, BatchID, SessionData)
    batch_faculty_map = {} # (BatchID) -> Set of Faculty Names
    
    for tt in all_timetables:
        grid = tt.get('timetable', {})
        b_id = tt.get('batch_id')
        if b_id not in batch_faculty_map: batch_faculty_map[b_id] = set()

        for day in grid:
            for slot, session in grid[day].items():
                if session and 'faculty_name' in session:
                    fname = session['faculty_name']
                    global_busy_map.add((fname, day, slot))
                    batch_faculty_map[b_id].add(fname)
                    
                    if fname not in faculty_slots: faculty_slots[fname] = []
                    faculty_slots[fname].append({
                        'day': day, 
                        'slot': slot, 
                        'batch_id': b_id,
                        'session': session
                    })
                    
                    # Identify our target slots to substitute
                    if fname == faculty_name and day in affected_day_names:
                        affected_slots.append({
                            'timetable_id': tt['_id'],
                            'batch_id': b_id,
                            'day': day,
                            'slot': slot,
                            'original_session': session
                        })
    
    # 3. Find Substitutes & Compensatory Swaps
    all_faculty = [f['name'] for f in db.faculty.find() if f['name'] != faculty_name]
    
    substitutions = []
    modifications_to_apply = [] 
    
    def get_candidate_course(candidate_name, target_batch_id):
        # Look up what course this candidate teaches to this batch
        if candidate_name in faculty_slots:
            for cls in faculty_slots[candidate_name]:
                if cls['batch_id'] == target_batch_id:
                    return cls['session'].get('code'), cls['session'].get('name')
        return None, None

    for item in affected_slots:
        day = item['day']
        slot = item['slot']
        item_batch_id = item['batch_id']
        
        # Prioritize Faculty who teach THIS BATCH
        priority_candidates = list(batch_faculty_map.get(item_batch_id, set()))
        priority_candidates = [f for f in priority_candidates if f != faculty_name and f in all_faculty]
        other_candidates = [f for f in all_faculty if f not in priority_candidates]
        
        # Merge lists, priority first
        candidate_list = priority_candidates + other_candidates
        
        candidate = None
        compensatory_slot = None
        
        # Strategy: Look for a Substitute who offers a Swap properly first
        for fac in candidate_list:
            # Check availability for the substitution slot
            if (fac, day, slot) not in global_busy_map:
                
                # Check for Compensatory Opportunity (Payback)
                if fac in faculty_slots:
                    for their_class in faculty_slots[fac]:
                        payback_day = their_class['day']
                        payback_slot = their_class['slot']
                        payback_batch = their_class['batch_id']
                        
                        # PRIORITY: Payback must be for the SAME BATCH if possible
                        if fac in priority_candidates and payback_batch != item_batch_id:
                            continue # Try to find a swap within the NEW batch logic

                        if payback_day == day and payback_slot == slot: continue
                        if payback_day in affected_day_names: continue 
                        
                        if (faculty_name, payback_day, payback_slot) not in global_busy_map:
                            # FOUND A SWAP!
                            candidate = fac
                            compensatory_slot = their_class
                            break
                
                if candidate: break 
                
        # If no swap found, fallback to simple substitution
        if not candidate:
            for fac in candidate_list:
                if (fac, day, slot) not in global_busy_map:
                    candidate = fac
                    break
        
        if candidate:
            # Determine Course Details for the Substitute
            sub_code, sub_name = get_candidate_course(candidate, item_batch_id)
            if not sub_code:
                # Fallback if they don't teach this batch regularily
                # Maybe they teach a subject that applies? 
                # For now, if unknown, use "SUB" and "Substitution" or keep original?
                # User asked to "put the course name and code of the substitued faculty"
                # If we don't know it, we can't put it. 
                # Let's try to find ANY course they teach and assume they teach that? No, that's risky.
                # Let's leave it as original if not found, OR mark as "Substitution".
                # But if it's a priority candidate, we SHOULD have found it.
                sub_code = "SUB"
                sub_name = "Substitute Class"
                
            # Plan Substitution
            modifications_to_apply.append({
                'timetable_id': item['timetable_id'],
                'batch_id': item['batch_id'],
                'day': day,
                'slot': slot,
                'faculty': candidate,
                'course_code': sub_code,
                'course_name': sub_name,
                'is_substitution': True,
                'substitued_for': faculty_name,
                'note': f"Subbing for {faculty_name}"
            })
            
            # Plan Compensation (if any)
            if compensatory_slot:
                comp_tt = db.timetables.find_one({'batch_id': compensatory_slot['batch_id']})
                if comp_tt:
                    # Original Faculty takes this slot. What course? The course Original Faculty teaches!
                    # Which is 'item['original_session']['code']' (from the slot they missed)
                    
                    modifications_to_apply.append({
                        'timetable_id': comp_tt['_id'],
                        'batch_id': compensatory_slot['batch_id'],
                        'day': compensatory_slot['day'],
                        'slot': compensatory_slot['slot'],
                        'faculty': faculty_name, 
                        'course_code': item['original_session'].get('code'),
                        'course_name': item['original_session'].get('name'),
                        'is_substitution': True,
                        'substitued_for': candidate,
                        'is_compensation': True,
                        'note': f"Compensatory class for {candidate}"
                    })
                    
            global_busy_map.add((candidate, day, slot))
            if compensatory_slot:
                 global_busy_map.add((faculty_name, compensatory_slot['day'], compensatory_slot['slot']))

    # 4. Apply Changes to DB
    modified_tt_ids = set()
    
    for mod in modifications_to_apply:
        tt_id = mod['timetable_id']
        if tt_id not in modified_tt_ids:
            original_tt = db.timetables.find_one({'_id': tt_id})
            if not original_tt: continue
            
            existing_temp = db.temporary_timetables.find_one({'original_tt_id': tt_id, 'leave_ref_id': ObjectId(leave_id)})
            
            if not existing_temp:
                new_tt = original_tt.copy()
                del new_tt['_id']
                new_tt['is_temporary'] = True
                new_tt['original_tt_id'] = tt_id
                new_tt['leave_ref_id'] = ObjectId(leave_id)
                new_tt['created_at'] = datetime.now()
                db.temporary_timetables.insert_one(new_tt)
            
            modified_tt_ids.add(tt_id)

    # Now Apply Updates
    for mod in modifications_to_apply:
        update_fields = {
            f'timetable.{mod["day"]}.{mod["slot"]}.faculty_name': mod['faculty'],
            f'timetable.{mod["day"]}.{mod["slot"]}.code': mod['course_code'],
            f'timetable.{mod["day"]}.{mod["slot"]}.name': mod['course_name'],
            f'timetable.{mod["day"]}.{mod["slot"]}.is_substitution': True,
            f'timetable.{mod["day"]}.{mod["slot"]}.substitued_for': mod['substitued_for']
        }
        if mod.get('is_compensation'):
             update_fields[f'timetable.{mod["day"]}.{mod["slot"]}.is_compensation'] = True
             update_fields[f'timetable.{mod["day"]}.{mod["slot"]}.compensation_note'] = mod['note']
        
        db.temporary_timetables.update_one(
            {'original_tt_id': mod['timetable_id'], 'leave_ref_id': ObjectId(leave_id)},
            {'$set': update_fields}
        )

    return len(modifications_to_apply)
