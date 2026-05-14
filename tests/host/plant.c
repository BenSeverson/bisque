#include "plant.h"

#include <math.h>

void plant_init(plant_t *p, float start_temp_c)
{
    p->temp_c = start_temp_c;
    p->ambient_c = 20.0f;
    p->tau_track_s = 3.0f;
    p->tau_cool_s = 300.0f;
    p->runaway_rate_c_per_s = 0.0f;
    p->stuck = false;
}

void plant_step(plant_t *p, float setpoint_c, float dt_s)
{
    if (p->stuck) {
        return;
    }
    if (p->runaway_rate_c_per_s > 0.0f) {
        p->temp_c += p->runaway_rate_c_per_s * dt_s;
        return;
    }
    /* Track setpoint with a first-order lag. If the engine is idle (setpoint
     * 0), drift gently toward ambient. */
    float target = (setpoint_c > 0.0f) ? setpoint_c : p->ambient_c;
    float tau = (setpoint_c > 0.0f) ? p->tau_track_s : p->tau_cool_s;
    float approach = 1.0f - expf(-dt_s / tau);
    p->temp_c += (target - p->temp_c) * approach;
}
