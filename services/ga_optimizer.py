import random
from services.fitness import compute_fitness
from services.mutations import swap_two_theory_sessions

class GeneticOptimizer:
    def __init__(self, base_scheduler, population_size=8, generations=10):
        self.base_scheduler = base_scheduler
        self.population_size = population_size
        self.generations = generations
        self.fitness_history = []

    def generate_initial_population(self):
        population = []
        for _ in range(self.population_size):
            # Check if scheduler has strict_mode_flag, else Default True
            strict = getattr(self.base_scheduler, 'strict_mode_flag', True)
            
            tt, _ = self.base_scheduler.allocate(strict_mode=strict)
            population.append(tt)
        return population

    def run(self, log_fn=None):
        if log_fn: log_fn(f"Initializing Population ({self.population_size})...")
        population = self.generate_initial_population()

        best_solution = None
        best_score = float('-inf')

        for gen in range(1, self.generations + 1):
            # Evaluate
            scored = [(compute_fitness(p), p) for p in population]
            scored.sort(key=lambda x: x[0], reverse=True)

            score, solution = scored[0]
            self.fitness_history.append(score)

            if score > best_score:
                best_score = score
                best_solution = solution

            if log_fn:
                log_fn(f"GA Gen {gen} | Best Fitness = {score}")

            # Elitism (Keep top 30%)
            keep_n = max(1, int(self.population_size * 0.3))
            new_population = [p for _, p in scored[:keep_n]]

            # Reproduction / Mutation
            while len(new_population) < self.population_size:
                # Tournament Selection or Random from top 50%
                parent = random.choice(scored[:max(2, int(self.population_size*0.5))])[1]
                
                # Mutation (Swap) - simplified for now
                child = swap_two_theory_sessions(parent)
                new_population.append(child)

            population = new_population

        return best_solution, self.fitness_history
