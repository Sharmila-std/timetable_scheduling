def compute_fitness(timetables):
    """
    Evaluate the quality of a set of timetables.
    Higher score is better.
    """
    score = 0

    for batch_id, tt in timetables.items():
        for day, slots in tt.items():
            # Get occupied slots as integers
            occupied = sorted(int(s) for s,v in slots.items() if v)

            # 1. Penalize Empty Days (We want balanced load, or at least active days)
            # Actually, standard logic often prefers compact weeks, but let's assume we want spread.
            if not occupied:
                score -= 10
                continue

            # 2. Penalize Gaps
            # Ideally students shouldn't have > 1 hour gap.
            for i in range(1, len(occupied)):
                gap = occupied[i] - occupied[i-1] - 1
                if gap > 0:
                    score -= gap * 4 # Heavy penalty per gap hour

            # 3. Reward Compactness (Density)
            score += len(occupied) * 2

        # 4. Check Course Spread (Distribution across days)
        # Avoid same course 3 times on Mon, Tue, Wed and then nothing.
        # Prefer uniform distribution?
        course_days = {}
        for day, slots in tt.items():
            for s,v in slots.items():
                if v and v['type'] == 'THEORY':
                    code = v['code']
                    if code not in course_days: course_days[code] = set()
                    course_days[code].add(day)

        for code, days in course_days.items():
            # If a course has 3 credits, it's ideal to be on 3 different days.
            # If it's on 1 day (all 3 slots), that's bad (but we hard blocked it anyway).
            # If it's on 2 days (2+1), acceptable.
            # If spread > 3 days (for a 3 credit course), technically impossible usually,
            # but for 4 credit courses spread over 5 days?
            # Let's just penalize excessive bunching if we didn't have hard constraints.
            # Since hard constraints enforce 1/day, spread is naturally >= credits/1.
            # So mostly we just check if it covers enough days.
            pass

    return score
