// Standalone demo driver for the Tyranny shim. Connects to a running
// crpg_rle.core.env_server and steps it with random actions. Build the full
// trainer-linked env with build.sh instead; this is for wire-protocol testing.
#include "tyranny.h"

#define DEMO_OBS 21244
#define DEMO_ATNS 4

int main(int argc, char** argv) {
    Tyranny env;
    memset(&env, 0, sizeof(env));
    env.num_agents = 1;
    env.port = (argc > 1) ? atoi(argv[1]) : 7000;
    strcpy(env.host, "127.0.0.1");
    env.obs_size = DEMO_OBS;
    env.n_actions = DEMO_ATNS;

    env.observations = (float*)calloc(DEMO_OBS, sizeof(float));
    env.actions = (int*)calloc(DEMO_ATNS, sizeof(int));
    env.rewards = (float*)calloc(1, sizeof(float));
    env.terminals = (unsigned char*)calloc(1, sizeof(unsigned char));

    c_reset(&env);
    int act_sizes[DEMO_ATNS] = {64, 36, 4, 13};
    for (int i = 0; i < 100; i++) {
        for (int a = 0; a < DEMO_ATNS; a++) env.actions[a] = rand() % act_sizes[a];
        c_step(&env);
        printf("step %d: reward %.3f terminal %d\n", i, env.rewards[0], env.terminals[0]);
    }
    c_close(&env);
    free(env.observations);
    free(env.actions);
    free(env.rewards);
    free(env.terminals);
    return 0;
}
