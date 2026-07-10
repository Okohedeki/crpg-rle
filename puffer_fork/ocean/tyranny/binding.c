#include "tyranny.h"

// OBS_SIZE must match the env_server's flattened observation. It depends on the
// CRPGEnv pixel resolution + state size; set it to match your config and rebuild.
// Default here is for a downscaled 84x84x3 pixel obs + 69 state + 1 mode + 6 goal.
#ifndef OBS_SIZE
#define OBS_SIZE 21244
#endif
#define NUM_ATNS 4
#define ACT_SIZES {64, 36, 4, 13}
#define OBS_TENSOR_T FloatTensor

#define Env Tyranny
#include "vecenv.h"

void my_init(Env* env, Dict* kwargs) {
    env->num_agents = 1;
    env->sockfd = 0;
    env->port = 7000;
    strcpy(env->host, "127.0.0.1");
    Value* port = dict_get(kwargs, "port");
    if (port != NULL) env->port = (int)port->value;
}

void my_log(Log* log, Dict* out) {
    dict_set(out, "score", log->score);
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
}
