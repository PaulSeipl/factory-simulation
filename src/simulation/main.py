from simpy import Environment, Interrupt

env = Environment()

class Car(object):
    def __init__(self, env: Environment):
        self.env = env
        # Start the run process everytime an instance is created
        self.action = env.process(self.run())
    
    def run(self):
        while True:
            print('Start parking and charging at %d' % self.env.now)
            charge_duration = 5
            try:
                yield self.env.process(self.charge(charge_duration))
            except Interrupt:
                print('Was interrupted at %d. Hope, the battery is full enough ...' % self.env.now)
                
            # The charge process has finished and
            # we can start driving again
            print('Start driving at %d' % env.now)
            trip_duration = 2
            yield env.timeout(trip_duration)
            
    def charge(self, duration):
        yield self.env.timeout(duration)
        
def driver(env:Environment, car: Car):
    yield env.timeout(3)
    car.action.interrupt()
        
car = Car(env)
env.process(driver(env, car))
env.run(until=15)