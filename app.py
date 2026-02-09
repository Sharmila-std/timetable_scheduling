from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
import bcrypt
from functools import wraps
from bson.objectid import ObjectId
from datetime import datetime
import secrets
from flask import Response, stream_with_context
from services.email_service import send_timetable_update_email, send_original_timetable_email

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a random secret key

# MongoDB Connection
# user provided: mongodb+srv://sharmila:123456_sharmila@capstone.3xycmpu.mongodb.net/?appName=capstone
# DB_NAME=se_tt
MONGO_URI = "mongodb+srv://sharmila:123456_sharmila@capstone.3xycmpu.mongodb.net/?appName=capstone"
client = MongoClient(MONGO_URI)
db = client['se_tt']
users_collection = db['users']
faculty_collection = db['faculty']
courses_collection = db['courses']
rooms_collection = db['rooms']
batches_collection = db['batches']
labs_collection = db['labs']
constraints_collection = db['constraints']
soft_constraints_collection = db['soft_constraints']
availability_collection = db['availability']
timetables_collection = db['timetables']
batch_generation_request_collection = db['batch_generation_request']
generation_logs_collection = db['generation_logs']
resource_availability_collection = db['resource_availability']

# Helper Functions
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def verify_password(stored_password, provided_password):
    return bcrypt.checkpw(provided_password.encode('utf-8'), stored_password)

# Login Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] != role:
                flash("Unauthorized access!", "danger")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        id_number = request.form['id_number']
        password = request.form['password']
        role = request.form['role']
        batch_id = request.form.get('batch_id') # Get batch if student

        if users_collection.find_one({'id_number': id_number}):
            flash('ID Number already exists!', 'danger')
            return redirect(url_for('register'))
        
        if users_collection.find_one({'email': email}):
             flash('Email already exists!', 'danger')
             return redirect(url_for('register'))

        hashed_password = hash_password(password)
        
        user_data = {
            'name': name,
            'email': email,
            'id_number': id_number,
            'password': hashed_password,
            'role': role
        }
        
        if role == 'student' and batch_id:
            user_data['batch_id'] = ObjectId(batch_id)
        
        users_collection.insert_one(user_data)
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    # Fetch batches for student registration
    batches = list(batches_collection.find())
    return render_template('register.html', batches=batches)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        id_number = request.form['id_number']
        password = request.form['password']
        
        user = users_collection.find_one({'id_number': id_number})
        
        if user and verify_password(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['name'] = user['name']
            session['role'] = user['role']
            
            if user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
            elif user['role'] == 'faculty':
                return redirect(url_for('faculty_dashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid ID or Password', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))



@app.route('/faculty')
@login_required
@role_required('faculty')
def faculty_dashboard():
    # Calculate lectures today
    import datetime
    today_name = datetime.date.today().strftime("%a") # Mon, Tue...
    
    all_tts = list(timetables_collection.find())
    my_name = session['name']
    lectures_today = 0
    
    # Calculate lectures today
    import datetime
    today_name = datetime.date.today().strftime("%a") # Mon, Tue...
    
    today_name = datetime.date.today().strftime("%a") # Mon, Tue...
    
    all_tts = list(timetables_collection.find())
    my_name = session['name']
    lectures_today = 0
    
    for tt in all_tts:
        t_data = tt.get('timetable', {})
        if today_name in t_data:
                     lectures_today += 1

    # Check Advisor Role
    advisor_batch = batches_collection.find_one({'class_advisor': my_name})
    advisor_for = advisor_batch['name'] if advisor_batch else None

    return render_template('faculty_dashboard.html', name=session['name'], role='faculty', lectures_today=lectures_today, advisor_for=advisor_for)

@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    teachers = list(faculty_collection.find())
    courses = list(courses_collection.find())
    rooms = list(rooms_collection.find())
    labs = list(labs_collection.find())
    batches = list(batches_collection.find())
    
    # Calculate Used Advisors
    used_advisors = set()
    for b in batches:
        if b.get('class_advisor'):
            used_advisors.add(b['class_advisor'])
            
    substitutions_count = db.temporary_timetables.count_documents({'is_temporary': True})
    return render_template('admin_dashboard.html', name=session['name'], teachers=teachers, courses=courses, rooms=rooms, labs=labs, batches=batches, substitutions_count=substitutions_count, used_advisors=used_advisors)

# --- Admin CRUD Routes ---

# 1. Manage Teachers (Faculty)
@app.route('/admin/add_teacher', methods=['POST'])
@login_required
@role_required('admin')
def add_teacher():
    name = request.form.get('name')
    email = request.form.get('email')
    id_number = request.form.get('id_number')
    password = request.form.get('password') # In a real app, auto-generate or email this
    
    # Get lists of qualified courses and labs
    course_ids = request.form.getlist('course_ids')
    lab_ids = request.form.getlist('lab_ids')
    
    if users_collection.find_one({'id_number': id_number}):
        flash('ID already exists', 'danger')
        return redirect(url_for('admin_dashboard'))

    hashed_password = hash_password(password)
    
    # Add to Users collection for Login
    users_collection.insert_one({
        'name': name,
        'email': email,
        'id_number': id_number,
        'password': hashed_password,
        'role': 'faculty'
    })
    
    # Add to Faculty collection for Data Management
    faculty_collection.insert_one({
        'name': name,
        'email': email,
        'id_number': id_number,
        'password': hashed_password,
        'qualified_courses': course_ids,
        'qualified_labs': lab_ids
    })
    
    flash('Faculty added successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_teacher/<user_id>')
@login_required
@role_required('admin')
def delete_teacher(user_id):
    # Find faculty in faculty collection first to get ID Number
    faculty = faculty_collection.find_one({'_id': ObjectId(user_id)})
    if faculty:
        # Delete from Users collection using ID Number (since _id might be different)
        users_collection.delete_one({'id_number': faculty['id_number']})
        # Delete from Faculty collection
        faculty_collection.delete_one({'_id': ObjectId(user_id)})
        
    flash('Faculty removed successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_teacher/<user_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_teacher(user_id):
    if request.method == 'POST':
        # Find original faculty to get old ID
        faculty = faculty_collection.find_one({'_id': ObjectId(user_id)})
        
        name = request.form.get('name')
        email = request.form.get('email')
        id_number = request.form.get('id_number')
        password = request.form.get('password')
        course_ids = request.form.getlist('course_ids')
        lab_ids = request.form.getlist('lab_ids')
        
        # Update details in Faculty Collection
        update_data = {
            'name': name,
            'email': email,
            'id_number': id_number,
            'qualified_courses': course_ids,
            'qualified_labs': lab_ids
        }
        
        # Update details in Users Collection
        user_update_data = {
            'name': name,
            'email': email,
            'id_number': id_number
        }
        
        if password: # If new password provided
            hashed_password = hash_password(password)
            update_data['password'] = hashed_password
            user_update_data['password'] = hashed_password
            
        faculty_collection.update_one({'_id': ObjectId(user_id)}, {'$set': update_data})
        users_collection.update_one({'id_number': faculty['id_number']}, {'$set': user_update_data})
        
        flash('Faculty updated successfully', 'success')
        return redirect(url_for('admin_dashboard'))
        
    teacher = faculty_collection.find_one({'_id': ObjectId(user_id)})
    courses = list(courses_collection.find())
    labs = list(labs_collection.find())
    return render_template('edit_faculty.html', teacher=teacher, courses=courses, labs=labs, name=session['name'])

# 2. Manage Courses
@app.route('/admin/add_course', methods=['POST'])
@login_required
@role_required('admin')
def add_course():
    courses_collection.insert_one({
        'code': request.form.get('code'),
        'name': request.form.get('name'),
        'credits': request.form.get('credits'),
        'preferred_session': request.form.get('preferred_session') # New Field: FN, AN, or Any
    })
    flash('Course added successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_course/<course_id>')
@login_required
@role_required('admin')
def delete_course(course_id):
    courses_collection.delete_one({'_id': ObjectId(course_id)})
    flash('Course deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_course/<course_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_course(course_id):
    if request.method == 'POST':
        courses_collection.update_one({'_id': ObjectId(course_id)}, {'$set': {
            'code': request.form.get('code'),
            'name': request.form.get('name'),
            'credits': request.form.get('credits'),
            'preferred_session': request.form.get('preferred_session')
        }})
        flash('Course updated successfully', 'success')
        return redirect(url_for('admin_dashboard'))
        
    course = courses_collection.find_one({'_id': ObjectId(course_id)})
    return render_template('edit_course.html', course=course, name=session['name'])

# 3. Manage Rooms
@app.route('/admin/add_room', methods=['POST'])
@login_required
@role_required('admin')
def add_room():
    rooms_collection.insert_one({
        'number': request.form.get('number'),
        'type': request.form.get('type'), # Lecture Hall, Lab
        'capacity': request.form.get('capacity')
    })
    flash('Room added successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_room/<room_id>')
@login_required
@role_required('admin')
def delete_room(room_id):
    rooms_collection.delete_one({'_id': ObjectId(room_id)})
    flash('Room deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_room/<room_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_room(room_id):
    if request.method == 'POST':
        rooms_collection.update_one({'_id': ObjectId(room_id)}, {'$set': {
            'number': request.form.get('number'),
            'type': request.form.get('type'),
            'capacity': request.form.get('capacity')
        }})
        flash('Room updated successfully', 'success')
        return redirect(url_for('admin_dashboard'))
        
    room = rooms_collection.find_one({'_id': ObjectId(room_id)})
    return render_template('edit_room.html', room=room, name=session['name'])

# 4. Manage Labs
@app.route('/admin/add_lab', methods=['POST'])
@login_required
@role_required('admin')
def add_lab():
    labs_collection.insert_one({
        'code': request.form.get('code'),
        'name': request.form.get('name')
    })
    flash('Lab added successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_lab/<lab_id>')
@login_required
@role_required('admin')
def delete_lab(lab_id):
    labs_collection.delete_one({'_id': ObjectId(lab_id)})
    flash('Lab deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_lab/<lab_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_lab(lab_id):
    if request.method == 'POST':
        labs_collection.update_one({'_id': ObjectId(lab_id)}, {'$set': {
            'code': request.form.get('code'),
            'name': request.form.get('name')
        }})
        flash('Lab updated successfully', 'success')
        return redirect(url_for('admin_dashboard'))
        
    lab = labs_collection.find_one({'_id': ObjectId(lab_id)})
    return render_template('edit_lab.html', lab=lab, name=session['name'])

# 5. Manage Batches (Student Groups) with Allocation
@app.route('/admin/add_batch', methods=['POST'])
@login_required
@role_required('admin')
def add_batch():
    # Get lists of selected IDs (multi-select)
    course_ids = request.form.getlist('course_ids')
    lab_ids = request.form.getlist('lab_ids')
    
    batches_collection.insert_one({
        'name': request.form.get('name'), # e.g. "Year 1 - Sec A"
        'size': request.form.get('size'),
        'courses': course_ids, # List of Course ObjectIDs
        'labs': lab_ids,       # List of Lab ObjectIDs
        'class_advisor': request.form.get('class_advisor') # Store Advisor Name
    })
    flash('Batch added with allocations successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_batch/<batch_id>')
@login_required
@role_required('admin')
def delete_batch(batch_id):
    batches_collection.delete_one({'_id': ObjectId(batch_id)})
    flash('Batch deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_batch/<batch_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_batch(batch_id):
    if request.method == 'POST':
        course_ids = request.form.getlist('course_ids')
        lab_ids = request.form.getlist('lab_ids')
        
        batches_collection.update_one({'_id': ObjectId(batch_id)}, {'$set': {
            'name': request.form.get('name'),
            'size': request.form.get('size'),
            'courses': course_ids,
            'labs': lab_ids,
            'class_advisor': request.form.get('class_advisor')
        }})
        flash('Batch updated successfully', 'success')
        return redirect(url_for('admin_dashboard'))
        
    batch = batches_collection.find_one({'_id': ObjectId(batch_id)})
    courses = list(courses_collection.find())
    labs = list(labs_collection.find())
    teachers = list(faculty_collection.find())
    
    # Calculate used advisors (excluding current batch's advisor if any)
    all_batches = list(batches_collection.find())
    used_advisors = set()
    for b in all_batches:
        if b.get('class_advisor') and str(b['_id']) != batch_id:
            used_advisors.add(b['class_advisor'])

    return render_template('edit_batch.html', batch=batch, courses=courses, labs=labs, teachers=teachers, used_advisors=used_advisors, name=session['name'])
    return render_template('edit_batch.html', batch=batch, courses=courses, labs=labs, name=session['name'])

# --- EPIC 3: Constraint Engine Routes ---

@app.route('/admin/constraints/availability', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def constraint_faculty_availability():
    if request.method == 'POST':
        faculty_id = request.form.get('faculty_id')
        # Expecting a list of strings like "Mon_1", "Wed_3" representing UNAVAILABLE slots
        unavailable_slots = request.form.getlist('unavailable_slots')
        
        # Structure the data
        constraint_data = {
            "type": "HARD",
            "rule": "TEACHER_AVAILABILITY",
            "entity": "faculty",
            "entity_id": faculty_id,
            "data": {
                "unavailable_slots": unavailable_slots
            }
        }
        
        # Upsert: Update if exists, Insert if not
        constraints_collection.update_one(
            {"rule": "TEACHER_AVAILABILITY", "entity_id": faculty_id},
            {"$set": constraint_data},
            upsert=True
        )
        
        flash('Availability constraint saved successfully', 'success')
        return redirect(url_for('constraint_faculty_availability'))
        
    teachers = list(faculty_collection.find())
    # You might want to pass existing constraints to pre-fill the form (handled via simple fetch in real app, or pass all constraints)
    existing_constraints = list(constraints_collection.find({"rule": "TEACHER_AVAILABILITY"}))
    # Convert list to dict for easier lookup in template: {faculty_id: ['Mon_1', ...]}
    availability_map = {c['entity_id']: c['data']['unavailable_slots'] for c in existing_constraints}
    
    return render_template('constraints/faculty_availability.html', teachers=teachers, availability_map=availability_map, name=session['name'])

# --- EPIC 4: Scheduler Routes ---
from services.scheduler import create_timetable

@app.route('/admin/generate_timetable/<batch_id>')
@login_required
@role_required('admin')
def route_generate_timetable(batch_id):
    # Run the heuristic scheduler
    tt_data = create_timetable(batch_id, db)
    
    # Save to MongoDB
    # Delete existing if any for this batch
    timetables_collection.delete_one({'batch_id': ObjectId(batch_id)})
    
    timetables_collection.insert_one({
        'batch_id': ObjectId(batch_id),
        'timetable': tt_data,
        'created_at': datetime.now()
    })
    
    flash('Timetable generated successfully!', 'success')
    return redirect(url_for('view_timetable', batch_id=batch_id))

@app.route('/admin/timetable/view/<batch_id>')
@login_required
@role_required('admin')
def view_timetable(batch_id):
    tt_entry = timetables_collection.find_one({'batch_id': ObjectId(batch_id)})
    batch = batches_collection.find_one({'_id': ObjectId(batch_id)})
    
    if not tt_entry:
        flash('No timetable found. Generate one first.', 'warning')
        return redirect(url_for('admin_dashboard'))
        
    return render_template('timetable_view.html', timetable=tt_entry['timetable'], batch=batch, name=session['name'])

@app.route('/admin/constraints/rooms', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def constraint_rooms():
    if request.method == 'POST':
        room_id = request.form.get('room_id')
        allowed_types = request.form.getlist('allowed_types')
        dedicated_dept = request.form.get('dedicated_dept')
        
        constraint_data = {
            "type": "HARD",
            "rule": "ROOM_USAGE",
            "entity": "room",
            "entity_id": room_id,
            "data": {
                "allowed_types": allowed_types,
                "dedicated_dept": dedicated_dept
            }
        }
        
        constraints_collection.update_one(
            {"rule": "ROOM_USAGE", "entity_id": room_id},
            {"$set": constraint_data},
            upsert=True
        )
        
        flash('Room constraint saved successfully', 'success')
        return redirect(url_for('constraint_rooms'))
        
    rooms = list(rooms_collection.find())
    existing_constraints = list(constraints_collection.find({"rule": "ROOM_USAGE"}))
    constraints_map = {c['entity_id']: c['data'] for c in existing_constraints}
    
    return render_template('constraints/room_constraints.html', rooms=rooms, constraints_map=constraints_map, name=session['name'])

    return render_template('constraints/room_constraints.html', rooms=rooms, constraints_map=constraints_map, name=session['name'])

# --- EPIC 5 & 6: Optimization Routes ---

@app.route('/admin/generate_timetable_multi')
@login_required
@role_required('admin')
def generate_timetable_multi():
    batches = list(batches_collection.find())
    return render_template('generate_timetable.html', batches=batches, name=session['name'])

@app.route('/admin/start_generation', methods=['POST'])
@login_required
@role_required('admin')
def start_generation():
    batch_ids = request.form.getlist('batch_ids')
    
    if not batch_ids:
        flash('Please select at least one batch.', 'danger')
        return redirect(url_for('generate_timetable_multi'))
    
    # Create Request
    req_id = batch_generation_request_collection.insert_one({
        'batch_ids': [ObjectId(bid) for bid in batch_ids],
        'status': 'QUEUED',
        'created_at': datetime.now(),
        'logs': []
    }).inserted_id
    
    # In a real async app, trigger Celery task here.
    # For this demo, we might redirect to a monitor that triggers a simplified async process or just runs it (if we can block).
    # Ideally: Redirect to Monitor -> Monitor JS calls /api/run_generation/<req_id> -> API runs logic (streaming or synchronous update).
    
    return redirect(url_for('generation_monitor', req_id=req_id))

@app.route('/admin/monitor/<req_id>')
@login_required
@role_required('admin')
def generation_monitor(req_id):
    req = batch_generation_request_collection.find_one({'_id': ObjectId(req_id)})
    if not req:
        flash('Request not found', 'danger')
        return redirect(url_for('admin_dashboard'))
    return render_template('generation_monitor.html', req=req, name=session['name'])

@app.route('/admin/run_optimization/<req_id>')
@login_required
@role_required('admin')
def run_optimization(req_id):
    from services.optimization_engine import run_optimization_pipeline
    
    # We use stream_with_context to keep the request context active (if needed for db access)
    # and yield data chunk by chunk to the frontend.
    return Response(stream_with_context(run_optimization_pipeline(db, req_id)), mimetype='text/plain')

@app.route('/admin/timetable/view_multi/<req_id>')
@login_required
@role_required('admin')
def view_timetable_multi(req_id):
    req = batch_generation_request_collection.find_one({'_id': ObjectId(req_id)})
    if not req:
        flash('Request not found', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    # Fetch all generated timetables for this request
    # batches = list(batches_collection.find({'_id': {'$in': req['batch_ids']}}))
    # Actually, let's fetch timetables directly
    timetables = list(timetables_collection.find({'batch_id': {'$in': req['batch_ids']}}))
    
    # We need batch details for each timetable
    full_data = []
    
    all_courses = {c['_id']: c for c in courses_collection.find()}
    all_labs = {l['_id']: l for l in labs_collection.find()}

    # --- end inserted routes ---
    
    # Continue original function flow (if it was inside one, but here we are at module level in app.py)
    # Wait, the anchor point is inside a function? No, line 600 is inside view_timetable_multi.
    # I CANNOT insert routes INSIDE a function.
    # I must find the END of view_timetable_multi.
    
    for tt in timetables:
        batch = batches_collection.find_one({'_id': tt['batch_id']})
        
        # Enrich batch courses/labs with details
        if batch:
            enriched_courses = []
            for c_id in batch.get('courses', []):
                c_obj = all_courses.get(ObjectId(c_id))
                if c_obj:
                    enriched_courses.append({
                        'code': c_obj['code'],
                        'name': c_obj['name'],
                        'credits': c_obj.get('credits', 'N/A')
                    })
            batch['courses_enriched'] = enriched_courses # Store separately to avoid breaking other things
            
            enriched_labs = []
            for l_id in batch.get('labs', []):
                l_obj = all_labs.get(ObjectId(l_id))
                if l_obj:
                    enriched_labs.append({
                        'code': l_obj['code'],
                        'name': l_obj['name'],
                        'credits': 2 # Default for labs
                    })
            batch['labs_enriched'] = enriched_labs

        full_data.append({
            'batch': batch,
            'timetable': tt['timetable']
        })
        
    return render_template('final_timetable_multi.html', results=full_data, name=session['name'])

# --- Timetable Viewer Routes ---
@app.route('/admin/timetable_viewer')
@login_required
@role_required('admin')
def timetable_viewer():
    saved_batch_ids = timetables_collection.distinct('batch_id')
    saved_batches = list(batches_collection.find({'_id': {'$in': saved_batch_ids}}))
    return render_template('timetable_viewer.html', batches=saved_batches, name=session['name'])

@app.route('/admin/view_selected_timetables', methods=['POST'])
@login_required
@role_required('admin')
def view_selected_timetables():
    batch_ids = request.form.getlist('batch_ids')
    if not batch_ids:
        flash('Please select at least one batch.', 'warning')
        return redirect(url_for('timetable_viewer'))
    
    b_ids_obj = [ObjectId(bid) for bid in batch_ids]
    timetables = list(timetables_collection.find({'batch_id': {'$in': b_ids_obj}}))
    
    full_data = []
    all_courses = {c['_id']: c for c in courses_collection.find()}
    all_labs = {l['_id']: l for l in labs_collection.find()}
    
    for tt in timetables:
        batch = batches_collection.find_one({'_id': tt['batch_id']})
        if not batch: continue
        
        # Enrich
        batch_courses = []
        for c_id in batch.get('courses', []):
            try:
                oid = ObjectId(c_id)
                if oid in all_courses:
                    batch_courses.append(all_courses[oid])
            except: pass
            
        batch_labs = []
        for l_id in batch.get('labs', []):
            try:
                oid = ObjectId(l_id)
                if oid in all_labs:
                    lab_data = all_labs[oid].copy()
                    lab_data['credits'] = 2
                    batch_labs.append(lab_data)
            except: pass
            
        batch['courses_enriched'] = batch_courses
        batch['labs_enriched'] = batch_labs
        
        full_data.append({'batch': batch, 'timetable': tt['timetable']})
    
    return render_template('final_timetable_multi.html', results=full_data, name=session['name'])

# --- Student Portal Routes ---

@app.route('/student/dashboard')
@app.route('/student/my_schedule')
@login_required
@role_required('student')
def student_dashboard():
    # 1. Get User and Batch
    user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    if not user or 'batch_id' not in user:
        flash('Student record incomplete. No batch assigned.', 'danger')
        return redirect(url_for('index'))
    
    batch_id = user['batch_id']
    batch = batches_collection.find_one({'_id': ObjectId(batch_id)})
    
    # 2. Get Original Timetable
    original_tt = timetables_collection.find_one({'batch_id': batch_id})
    
    # 3. Get Substitutions
    substitutions_list = list(db.temporary_timetables.find({'batch_id': batch_id, 'is_temporary': True}))

    # MERGE LOGIC: Overlay substitutions onto original timetable
    import copy
    final_tt = copy.deepcopy(original_tt) if original_tt else {'timetable': {}}
    if 'timetable' not in final_tt: final_tt['timetable'] = {}

    for sub in substitutions_list:
        sub_tt = sub.get('timetable', {})
        for day, day_slots in sub_tt.items():
            if day not in final_tt['timetable']: final_tt['timetable'][day] = {}
            for slot, session_data in day_slots.items():
                if session_data:
                    # Check if actually different from original
                    is_diff = False
                    orig_day = original_tt.get('timetable', {}).get(day, {})
                    orig_slot = orig_day.get(slot)
                    
                    if not orig_slot:
                        # New slot where there was none
                        is_diff = True
                    else:
                        # Compare critical fields
                        if (orig_slot.get('code') != session_data.get('code') or
                            orig_slot.get('faculty_name') != session_data.get('faculty_name') or
                            orig_slot.get('room') != session_data.get('room')):
                            is_diff = True
                    
                    if is_diff:
                        session_data['is_substitution'] = True
                    
                    # Overlay onto final timetable (always overlay to ensure we have the latset data, 
                    # but only mark is_substitution if changed)
                    final_tt['timetable'][day][slot] = session_data

    
    # 4. Calculate "Today's Schedule" from FINAL MERGED TIMETABLE
    import datetime
    today_name = datetime.date.today().strftime("%a") # Mon, Tue, etc.
    today_schedule = []
    
    if final_tt and 'timetable' in final_tt and today_name in final_tt['timetable']:
        day_slots = final_tt['timetable'][today_name]
        for slot_num, session_data in day_slots.items():
            if not session_data: continue
            today_schedule.append({
                'slot': slot_num,
                'course_code': session_data['code'],
                'course_name': session_data['name'],
                'faculty': session_data['faculty_name'],
                'room': session_data['room'],
                'is_substitution': session_data.get('is_substitution', False)
            })

    # Sort by Slot
    today_schedule.sort(key=lambda x: int(x['slot']))

    return render_template('student_dashboard.html', 
                           name=session['name'], 
                           batch=batch, 
                           original_tt=final_tt, 
                           real_original_tt=original_tt,
                           today_schedule=today_schedule,
                           today_day=today_name,
                           substitutions=substitutions_list)

# --- Faculty Specific Routes ---

@app.route('/faculty/all_timetables')
@login_required
@role_required('faculty')
def faculty_all_timetables():
    saved_batch_ids = timetables_collection.distinct('batch_id')
    saved_batches = list(batches_collection.find({'_id': {'$in': saved_batch_ids}}))
    return render_template('faculty_timetable_viewer.html', batches=saved_batches, name=session['name'])

@app.route('/faculty/view_selected', methods=['POST'])
@login_required
@role_required('faculty')
def faculty_view_selected():
    batch_ids = request.form.getlist('batch_ids')
    if not batch_ids:
        flash('Please select at least one batch.', 'warning')
        return redirect(url_for('faculty_all_timetables'))
    
    b_ids_obj = [ObjectId(bid) for bid in batch_ids]
    timetables = list(timetables_collection.find({'batch_id': {'$in': b_ids_obj}}))
    
    full_data = []
    all_courses = {c['_id']: c for c in courses_collection.find()}
    all_labs = {l['_id']: l for l in labs_collection.find()}
    
    for tt in timetables:
        batch = batches_collection.find_one({'_id': tt['batch_id']})
        if not batch: continue
        
        batch_courses = []
        for c_id in batch.get('courses', []):
            try:
                oid = ObjectId(c_id)
                if oid in all_courses: batch_courses.append(all_courses[oid])
            except: pass
            
        batch_labs = []
        for l_id in batch.get('labs', []):
            try:
                oid = ObjectId(l_id)
                if oid in all_labs:
                    l_d = all_labs[oid].copy()
                    l_d['credits'] = 2
                    batch_labs.append(l_d)
            except: pass
            
        batch['courses_enriched'] = batch_courses
        batch['labs_enriched'] = batch_labs
        
        # Determine the Final Timetable to Display
        final_display_tt = tt['timetable'] # Default to what we fetched
        
        is_temp = tt.get('is_temporary', False)
        
        if is_temp:
            import copy
            # If it's a temporary chart, we MUST merge it onto the original to ensure 
            # we show the FULL schedule (in case temp is sparse) OR simply to be consistent.
            original_tt = timetables_collection.find_one({'batch_id': batch['_id']})
            
            if original_tt and 'timetable' in original_tt:
                # 1. Start with Original
                merged_tt = copy.deepcopy(original_tt['timetable'])
                
                # 2. Overlay the Temporary Data
                temp_data = tt.get('timetable', {})
                for day, day_slots in temp_data.items():
                    if day not in merged_tt: merged_tt[day] = {}
                    for slot_num, session_data in day_slots.items():
                        if session_data:
                             merged_tt[day][slot_num] = session_data
                
                # 3. Use this Merged TT as the display base
                final_display_tt = merged_tt
                
                # 4. Now Perform Diff to Highlight Changes
                # Compare final_display_tt (Merged) vs original_tt
                for day, day_slots in final_display_tt.items():
                    orig_day = original_tt['timetable'].get(day, {})
                    for slot_num, session_data in day_slots.items():
                        if not session_data: continue
                        
                        is_diff = False
                        orig_slot = orig_day.get(slot_num)
                        
                        if not orig_slot:
                             is_diff = True
                        else:
                            if (orig_slot.get('code') != session_data.get('code') or
                                orig_slot.get('faculty_name') != session_data.get('faculty_name') or
                                orig_slot.get('room') != session_data.get('room')):
                                is_diff = True
                        
                        if is_diff:
                            session_data['is_substitution'] = True

        full_data.append({
            'batch': batch, 
            'timetable': final_display_tt,
            'is_temporary': is_temp,
            'doc_id': tt['_id']
        })
    
    if not full_data:
        flash('No timetables found.', 'warning')
        return redirect(url_for('faculty_all_timetables'))

    return render_template('final_timetable_multi.html', results=full_data, name=session['name'])

@app.route('/faculty/my_schedule')
@login_required
@role_required('faculty')
def faculty_my_schedule():
    all_tts = list(timetables_collection.find())
    my_name = session['name']
    
    my_name = session['name']
    
    # Filter Logic
    filter_mode = request.args.get('filter')
    filter_day = None
    
    if filter_mode == 'today':
        import datetime
        today_name = datetime.date.today().strftime("%a")
        filter_day = today_name
    
    my_schedule = {d: {} for d in ["Mon", "Tue", "Wed", "Thu", "Fri"]}
    
    for tt_entry in all_tts:
        batch = batches_collection.find_one({'_id': tt_entry['batch_id']})
        batch_name = batch['name'] if batch else "Unknown Batch"
        timetable_grid = tt_entry.get('timetable', {})
        
        for day, slots in timetable_grid.items():
            if day not in my_schedule: continue
            for slot_num, session_data in slots.items():
                if not session_data: continue
                if session_data.get('faculty_name') == my_name:
                    class_info = {
                        'batch': batch_name,
                        'course_code': session_data['code'],
                        'course_name': session_data['name'],
                        'room': session_data['room'],
                        'type': session_data.get('type', 'Theory')
                    }
                    my_schedule[day][slot_num] = class_info
                    
    return render_template('faculty_personal_schedule.html', schedule=my_schedule, name=session['name'], filter_day=filter_day)

    return render_template('faculty_personal_schedule.html', schedule=my_schedule, name=session['name'])

# --- Leave Management Routes ---

@app.route('/faculty/apply_leave', methods=['GET', 'POST'])
@login_required
@role_required('faculty')
def faculty_apply_leave():
    db = client['timetable_db'] # Ensure db access
    leave_collection = db['leave_requests']
    
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        reason = request.form['reason']
        type_ = request.form['type']
        
        leave_collection.insert_one({
            'faculty_name': session['name'],
            'start_date': start_date,
            'end_date': end_date,
            'reason': reason,
            'type': type_,
            'status': 'Pending',
            'created_at': datetime.now()
        })
        flash('Leave request submitted successfully.', 'success')
        return redirect(url_for('faculty_apply_leave'))
        
    # Get History
    history = list(leave_collection.find({'faculty_name': session['name']}).sort('created_at', -1))
    return render_template('faculty_apply_leave.html', history=history, name=session['name'])

@app.route('/admin/leave_requests')
@login_required
@role_required('admin')
def admin_leave_requests():
    db = client['timetable_db']
    requests = list(db['leave_requests'].find().sort('created_at', -1))
    return render_template('admin_leave_requests.html', requests=requests, name=session['name'])

@app.route('/admin/manage_leave/<id>', methods=['POST'])
@login_required
@role_required('admin')
def manage_leave(id):
    db = client['timetable_db']
    action = request.form.get('action')
    status = 'Approved' if action == 'approve' else 'Rejected'
    
    db['leave_requests'].update_one({'_id': ObjectId(id)}, {'$set': {'status': status}})
    flash(f'Leave request {status}.', 'success')
    return redirect(url_for('admin_leave_requests'))

# --- Substitution Routes ---
from services.substitution_service import generate_substitution_plan

@app.route('/admin/generate_substitution/<leave_id>', methods=['POST'])
@login_required
@role_required('admin')
def generate_substitution(leave_id):
    count = generate_substitution_plan(leave_id)
    if count is not None and count > 0:
        flash(f'Substitution Plan Generated! {count} classes reassigned.', 'success')
    else:
        flash('No classes found to substitute or error occurred.', 'warning')
    return redirect(url_for('admin_leave_requests'))

@app.route('/admin/view_substitutions')
@login_required
@role_required('admin')
def view_substitutions():
    # Fetch all temporary timetables
    temp_tts = list(db.temporary_timetables.find({'is_temporary': True}))
    
    # Enrich data
    full_data = []
    for tt in temp_tts:
        batch = batches_collection.find_one({'_id': tt['batch_id']})
        if batch:
            full_data.append({'batch': batch, 'timetable': tt['timetable'], 'id': tt['_id']})
            
    return render_template('admin_substitution_view.html', results=full_data, name=session['name'])

@app.route('/admin/delete_substitution/<id>')
@login_required
@role_required('admin')
def delete_substitution(id):
    db.temporary_timetables.delete_one({'_id': ObjectId(id)})
    flash('Substitution plan deleted successfully.', 'success')
    return redirect(url_for('view_substitutions'))

@app.route('/admin/notify_advisor/<id>')
@login_required
@role_required('admin')
def notify_advisor(id):
    # 1. Fetch Substitution Data
    temp_tt = db.temporary_timetables.find_one({'_id': ObjectId(id)})
    if not temp_tt:
        flash('Substitution plan not found.', 'danger')
        return redirect(url_for('view_substitutions'))
        
    # 2. Fetch Original Data
    original_tt = db.timetables.find_one({'_id': temp_tt['original_tt_id']})
    
    # 3. Fetch Batch & Advisor
    batch = batches_collection.find_one({'_id': ObjectId(temp_tt['batch_id'])})
    if not batch:
        flash('Batch not found.', 'danger')
        return redirect(url_for('view_substitutions'))
        
    advisor_name = batch.get('class_advisor')
    if not advisor_name:
        flash(f'No Class Advisor assigned for batch {batch["name"]}.', 'warning')
        return redirect(url_for('view_substitutions'))
        
    # 4. Fetch Advisor Email from Faculty Collection
    advisor = faculty_collection.find_one({'name': advisor_name})
    if not advisor or 'email' not in advisor:
        flash(f'Email not found for advisor {advisor_name}.', 'danger')
        return redirect(url_for('view_substitutions'))
        
    advisor_email = advisor['email']
    
    # 5. Send Email
    success = send_timetable_update_email(advisor_email, batch['name'], original_tt, temp_tt)
    
    if success:
        flash(f'Notification sent to {advisor_name} ({advisor_email}).', 'success')
    else:
        flash('Failed to send email. Check server logs/configuration.', 'danger')
        
    if success:
        flash(f'Notification sent to {advisor_name} ({advisor_email}).', 'success')
    else:
        flash('Failed to send email. Check server logs/configuration.', 'danger')
        
    return redirect(url_for('view_substitutions'))

@app.route('/admin/email_original_tt/<batch_id>')
@login_required
@role_required('admin')
def email_original_tt(batch_id):
    # 1. Fetch Batch
    batch = batches_collection.find_one({'_id': ObjectId(batch_id)})
    if not batch:
        flash('Batch not found.', 'danger')
        return redirect(url_for('timetable_viewer'))
        
    # 2. Fetch Original Timetable
    # 2. Fetch Original Timetable
    original_tt = timetables_collection.find_one({'batch_id': ObjectId(batch_id)})
    if not original_tt:
        flash('Original timetable not found.', 'danger')
        return redirect(url_for('timetable_viewer'))
    
    # 3. Check Advisor
    advisor_name = batch.get('class_advisor')
    if not advisor_name:
        flash(f'No Class Advisor assigned for batch {batch["name"]}.', 'warning')
        return redirect(url_for('timetable_viewer'))
        
    # 4. Fetch Advisor Email
    advisor = faculty_collection.find_one({'name': advisor_name})
    if not advisor or 'email' not in advisor:
        flash(f'Email not found for advisor {advisor_name}.', 'danger')
        return redirect(url_for('timetable_viewer'))
        
    advisor_email = advisor['email']
    
    # 5. Send Email
    success = send_original_timetable_email(advisor_email, batch['name'], original_tt)
    
    if success:
        flash(f'Original Timetable sent to {advisor_name} ({advisor_email}).', 'success')
    else:
        flash('Failed to send email.', 'danger')
        
    return redirect(url_for('timetable_viewer'))

# --- API Endpoints for View Logic ---
from flask import jsonify

@app.route('/api/faculty/<id>')
@login_required
def api_get_faculty(id):
    try:
        f = faculty_collection.find_one({'_id': ObjectId(id)})
        if not f: return jsonify({'error': 'Not found'}), 404
        
        # Resolve course/lab names
        courses = list(courses_collection.find({'_id': {'$in': [ObjectId(c) for c in f.get('qualified_courses', [])]}}))
        labs = list(labs_collection.find({'_id': {'$in': [ObjectId(l) for l in f.get('qualified_labs', [])]}}))
        
        return jsonify({
            'title': f['name'],
            'details': {
                'Name': f['name'],
                'Email': f['email'],
                'ID Number': f['id_number'],
                'Qualified Courses': [{'code': c['code'], 'name': c['name'], 'credits': c.get('credits', 'N/A')} for c in courses],
                'Qualified Labs': [{'code': l['code'], 'name': l['name']} for l in labs]
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/course/<id>')
@login_required
def api_get_course(id):
    try:
        c = courses_collection.find_one({'_id': ObjectId(id)})
        if not c: return jsonify({'error': 'Not found'}), 404
        return jsonify({
            'title': f"{c['code']} - {c['name']}",
            'details': {
                'Code': c['code'],
                'Name': c['name'],
                'Credits': c.get('credits', 'N/A'),
                'Preferred Session': c.get('preferred_session', 'Any')
            }
        })
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/lab/<id>')
@login_required
def api_get_lab(id):
    try:
        l = labs_collection.find_one({'_id': ObjectId(id)})
        if not l: return jsonify({'error': 'Not found'}), 404
        return jsonify({
            'title': f"{l['code']} - {l['name']}",
            'details': {
                'Code': l['code'],
                'Name': l['name']
            }
        })
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/room/<id>')
@login_required
def api_get_room(id):
    try:
        r = rooms_collection.find_one({'_id': ObjectId(id)})
        if not r: return jsonify({'error': 'Not found'}), 404
        return jsonify({
            'title': f"Room {r['number']}",
            'details': {
                'Number': r['number'],
                'Type': r['type'],
                'Capacity': r.get('capacity', 'N/A')
            }
        })
    except: return jsonify({'error': 'Error'}), 500

@app.route('/api/batch/<id>')
@login_required
def api_get_batch(id):
    try:
        b = batches_collection.find_one({'_id': ObjectId(id)})
        if not b: return jsonify({'error': 'Not found'}), 404
        
        courses = list(courses_collection.find({'_id': {'$in': [ObjectId(c) for c in b.get('courses', [])]}}))
        labs = list(labs_collection.find({'_id': {'$in': [ObjectId(l) for l in b.get('labs', [])]}}))
        
        return jsonify({
            'title': b['name'],
            'details': {
                'Group Name': b['name'],
                'Size': b.get('size', 0),
                'Class Advisor': b.get('class_advisor', 'Not Assigned'),
                'Assigned Courses': [{'code': c['code'], 'name': c['name'], 'credits': c.get('credits', 'N/A')} for c in courses],
                'Assigned Labs': [{'code': l['code'], 'name': l['name']} for l in labs]
            }
        })
    except Exception as e: return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
