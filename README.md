Timetable Management System

A comprehensive web-based application for managing and generating university/college timetables using Flask and MongoDB. This system streamlines the process of scheduling classes, managing faculty availability, and communicating schedule changes to students and staff.

Features

 for Administrators
*   Resource Management: CRUD operations for Teachers, Courses, Labs, Rooms, and Student Batches.
*   Constraint Management: Define hard and soft constraints such as Faculty Availability and Room Usage rules.
*   Timetable Generation:
    *   Heuristic Scheduler: Quick generation based on predefined rules.
    *   Optimization Engine: Advanced scheduling using Genetic Algorithms (GA) to minimize conflicts and optimize resource usage.
    *   Batch Generation: Generate timetables for multiple batches simultaneously.
*   Monitoring: Real-time monitoring of generation tasks.
*   Substitution Management: Handle temporary timetable changes and substitutions.

for Faculty
*   Dashboard: View daily teaching schedule and total lecture count.
*   Advisorship: View details of the batch they are advising.

for Students
*   Personalized Portal: View assigned batch timetable.
*   Real-time Updates: See temporary substitutions and schedule changes (highlighted for visibility).
*   Profile Management: Registration with batch selection.

Tech Stack

*   Backend: Python, Flask
*   Database: MongoDB (via pymongo)
*   Authentication: bcrypt (Password hashing), Session-based auth
*   Frontend: HTML5, CSS3, JavaScript (Jinja2 Templates)
*   Logic: Custom Genetic Algorithm implementation for scheduling optimization


Installation & Setup

1.  Clone the repository
    bash
    git clone <repository-url>
    cd <project-directory>
    

2.  Create a Virtual Environment (Optional but Recommended)
    bash
    python -m venv venv
    - Windows
    venv\Scripts\activate
    - macOS/Linux
    source venv/bin/activate
    

3.  **Install Dependencies**
    bash
    pip install -r requirements.txt
    

4.  Configuration
    *   Ensure your MongoDB instance is running.
    *   Update the MONGO_URI in app.py if necessary (currently configured for a cloud instance).

5.  Run the Application
    bash
    python app.py
   
    The application will be available at http://127.0.0.1:5000/.

Usage Guide

1.  Register/Login: Start by registering an Admin account (or use existing credentials).
2.  Populate Data: Go to the Admin Dashboard to add Rooms, Labs, Courses, and Faculty.
3.  Create Batches: Define student batches and assign courses/labs.
4.  Set Constraints: details specific availability for faculty or room restrictions.
5.  Generate: Use the "Generate Timetable" feature for specific batches or centrally for all.

