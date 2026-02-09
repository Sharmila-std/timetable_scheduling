from pymongo import MongoClient
from bson.objectid import ObjectId

client = MongoClient("mongodb+srv://sharmila:123456_sharmila@capstone.3xycmpu.mongodb.net/?appName=capstone")
db = client['se_tt']

print("\n--- ALL LEAVE REQUESTS ---")
for req in db.leave_requests.find():
    print(f"ID: '{req['_id']}' | Name: {req.get('faculty_name')} | Status: {req.get('status')}")
print("--------------------------\n")
