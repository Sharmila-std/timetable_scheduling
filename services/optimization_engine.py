import time
import random
from datetime import datetime
from bson import ObjectId

class OptimizationScheduler:
    def __init__(self, db, req_id):
        self.db = db
        self.req_id = req_id
        self.req = db.batch_generation_request.find_one({'_id': ObjectId(req_id)})
        self.batches = list(db.batches.find({'_id': {'$in': self.req['batch_ids']}}))
        self.logs = []

    def log(self, message):
        """Log to database and yield for streaming."""
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self.logs.append(entry)
        # Update db logs (optional, maybe execute in bulk later to save DB hits)
        # self.db.batch_generation_request.update_one(...)
        return f"{entry}\n"

    def run(self):
        """
        Main Pipeline:
        1. Session Expansion
        2. Conflict Graph Construction
        3. Graph Coloring (DSATUR)
        4. Genetic Algorithm Optimization
        """
        yield "STATUS:INITIALIZING\n"
        yield self.log(f"Starting Optimization for {len(self.batches)} batches...")
        time.sleep(1)

        # --- Phase 1: Session Expansion ---
        yield "PROGRESS:10\n"
        yield "STATUS:EXPANDING SESSIONS\n"
        yield self.log("Phase 1: Expanding Courses into Sessions...")
        
        total_sessions = 0
        sessions = []
        for batch in self.batches:
            yield self.log(f"Processing Batch: {batch['name']}")
            # Mocking specific session creation
            courses = list(self.db.courses.find({'_id': {'$in': [ObjectId(c) for c in batch['courses']]}}))
            for c in courses:
                count = int(c.get('credits', 3))
                total_sessions += count
                sessions.append({'batch': batch['name'], 'course': c['code'], 'type': 'Theory'})
            
            labs = list(self.db.labs.find({'_id': {'$in': [ObjectId(l) for l in batch['labs']]}}))
            for l in labs:
                total_sessions += 1 # Labs are 1 block
                sessions.append({'batch': batch['name'], 'course': l['code'], 'type': 'Lab'})
            
            time.sleep(0.5)

        yield self.log(f"Total Sessions to Schedule: {total_sessions}")
        time.sleep(1)

        # --- Phase 2: Unified Optimization ---
        yield "PROGRESS:30\n"
        yield "STATUS:BUILDING GRAPH\n"
            
        # PHASE 1: Data Preparation
        yield self.log("Phase 1: Preparing Data & Constraints...")
        
        # PHASE 2: (Legacy Graph steps skipped for Unified Scheduler)
        # PHASE 3: (Legacy DSATUR skipped - moved to scheduler internal)
        # PHASE 4: (Legacy GA skipped - moved to scheduler internal)

        # PHASE 5: Optimization
        yield self.log("Phase 2: Launching Unified GA Optimization Pipeline...")
        
        # Call the new Custom GA Scheduler
        from services.custom_ga_optimizer import run_custom_ga
        import traceback
        
        # We pass a lambda for logging to bridge the gap (though the generator handles it now)
        # run_custom_ga returns a generator yielding ("LOG", msg) or ("RESULT", data)
        
        all_timetables = {}
        fitness_curve = []
        
        gen = run_custom_ga(self.db, self.req['batch_ids'])
        
        try:
            for event_type, payload in gen:
                if event_type == "LOG":
                    yield self.log(payload)
                elif event_type == "RESULT":
                    all_timetables, fitness_curve = payload
                    
        except Exception as e:
            yield self.log(f"Optimization Error: {str(e)}")
            raise e
        
        yield self.log(f"  > Scheduler returned {len(all_timetables)} timetables.")
        yield self.log(f"  > Final Fitness: {fitness_curve[-1] if fitness_curve else 'N/A'}")
            
        # --- Phase 5: Finalization ---
        yield "PROGRESS:90\n"
        yield "STATUS:FINALIZING\n"
        yield self.log("Phase 5: Committing Timetables...")
        
        try:
            # Save results
            for batch_id, tt_data in all_timetables.items():
                batch_name = "Batch"
                b = next((b for b in self.batches if b['_id'] == batch_id), None)
                b_name = b['name'] if b else str(batch_id)
                
                yield self.log(f"  > Saving Timetable for {b_name}...")
                
                self.db.timetables.delete_one({'batch_id': batch_id})
                self.db.timetables.insert_one({
                    'batch_id': batch_id,
                    'timetable': tt_data,
                    'created_at': datetime.now(),
                    'generated_by_request': self.req_id
                })
            
            # Update request status AND Fitness Curve
            self.db.batch_generation_request.update_one(
                {'_id': ObjectId(self.req_id)},
                {'$set': {
                    'status': 'COMPLETED', 
                    'logs': self.logs,
                    'fitness_curve': fitness_curve
                }}
            )

            yield self.log("Optimization Pipeline Completed Successfully! 🚀")
            yield "PROGRESS:100\n"
            yield "STATUS:COMPLETED\n"
            yield "DONE\n"
            
        except Exception as e:
            yield self.log(f"FATAL PIPELINE ERROR: {str(e)}")
            yield self.log(traceback.format_exc().replace('\n', '<br>'))
            yield "STATUS:FAILED\n"
            # Ensure we don't hang the UI
            yield "DONE\n"

def run_optimization_pipeline(db, req_id):
    scheduler = OptimizationScheduler(db, req_id)
    return scheduler.run()
