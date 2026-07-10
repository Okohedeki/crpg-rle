// Tyranny env shim for PufferLib 4.0.
//
// PufferLib 4.0 compiles each env into _C.so and steps it in a synchronous
// OpenMP loop; there is no out-of-process env path. This shim IS a normal
// Ocean env whose c_step blocks on a TCP round-trip to a Python env_server
// (crpg_rle.core.env_server) running on the game host, which owns the live
// Tyranny process. The shim only marshals arrays; all game logic is in Python.
//
// Protocol (little-endian), mirrors crpg_rle/core/env_server.py:
//   handshake:  -> "CRPG", u32 proto      <- u32 obs_size, u32 n_actions, u64 base_seed
//   step:       -> int32[n_actions]       <- f32[obs_size], f32 reward, u8 term, u8 trunc
// On terminal the server auto-resets and returns the next episode's first obs.
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#endif

typedef struct {
    float perf;
    float score;
    float episode_return;
    float episode_length;
    // Per-episode learning metrics (order matches env_server's log_metrics /
    // TyrannyAdapter.LOG_METRIC_NAMES). PufferLib divides these sums by n.
    float r_milestone;
    float r_faction_favor;
    float milestones_reached;
    float term_success;
    float term_failure;
    float term_timer;
    float frac_combat;
    float frac_dialogue;
    float frac_overworld;
    float frac_levelup;
    float n;
} Log;

// Number of float metrics in the per-step trailer (must equal len of
// TyrannyAdapter.LOG_METRIC_NAMES / env_server n_extra).
#define TY_N_EXTRA 10

typedef struct {
    Log log;                     // required
    float* observations;         // required (FloatTensor)
    int* actions;                // required
    float* rewards;              // required
    unsigned char* terminals;    // required
    int num_agents;              // required

    int sockfd;
    int obs_size;
    int n_actions;
    int n_extra;
    int port;
    char host[64];
    float ep_return;
    float ep_len;
} Tyranny;

static int recv_all(int fd, void* buf, int n) {
    char* p = (char*)buf;
    int got = 0;
    while (got < n) {
        int r = recv(fd, p + got, n - got, 0);
        if (r <= 0) return -1;
        got += r;
    }
    return 0;
}

static int send_all(int fd, const void* buf, int n) {
    const char* p = (const char*)buf;
    int sent = 0;
    while (sent < n) {
        int r = send(fd, p + sent, n - sent, 0);
        if (r <= 0) return -1;
        sent += r;
    }
    return 0;
}

static void ty_connect(Tyranny* env) {
#ifdef _WIN32
    WSADATA wsa; WSAStartup(MAKEWORD(2, 2), &wsa);
#endif
    env->sockfd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((unsigned short)env->port);
    inet_pton(AF_INET, env->host[0] ? env->host : "127.0.0.1", &addr.sin_addr);
    if (connect(env->sockfd, (struct sockaddr*)&addr, sizeof(addr)) != 0) {
        fprintf(stderr, "tyranny shim: connect to %s:%d failed\n", env->host, env->port);
        exit(1);
    }
    int one = 1;
    setsockopt(env->sockfd, IPPROTO_TCP, TCP_NODELAY, (const char*)&one, sizeof(one));

    // handshake
    send_all(env->sockfd, "CRPG", 4);
    unsigned int proto = 1;
    send_all(env->sockfd, &proto, 4);
    unsigned int obs_size = 0, n_actions = 0, n_extra = 0;
    unsigned long long base_seed = 0;
    recv_all(env->sockfd, &obs_size, 4);
    recv_all(env->sockfd, &n_actions, 4);
    recv_all(env->sockfd, &base_seed, 8);
    recv_all(env->sockfd, &n_extra, 4);
    env->obs_size = (int)obs_size;
    env->n_actions = (int)n_actions;
    env->n_extra = (int)n_extra;
    // first obs
    recv_all(env->sockfd, env->observations, env->obs_size * (int)sizeof(float));
}

void c_reset(Tyranny* env) {
    if (env->sockfd == 0) ty_connect(env);
    // Reset is server-driven (auto-reset on terminal). Nothing to do here after
    // the handshake delivered the first observation.
    env->ep_return = 0;
    env->ep_len = 0;
}

void c_step(Tyranny* env) {
    // Send the action ints, block for the next obs + reward + terminal.
    send_all(env->sockfd, env->actions, env->n_actions * (int)sizeof(int));
    recv_all(env->sockfd, env->observations, env->obs_size * (int)sizeof(float));
    float reward = 0.0f;
    unsigned char term = 0, trunc = 0;
    recv_all(env->sockfd, &reward, 4);
    recv_all(env->sockfd, &term, 1);
    recv_all(env->sockfd, &trunc, 1);

    // Per-step learning-metric trailer (zeros except on the episode-ending step).
    float extra[TY_N_EXTRA];
    memset(extra, 0, sizeof(extra));
    if (env->n_extra > 0) {
        int n = env->n_extra < TY_N_EXTRA ? env->n_extra : TY_N_EXTRA;
        recv_all(env->sockfd, extra, n * (int)sizeof(float));
    }

    env->rewards[0] = reward;
    env->terminals[0] = term;
    env->ep_return += reward;
    env->ep_len += 1;
    if (term || trunc) {
        env->log.episode_return += env->ep_return;
        env->log.episode_length += env->ep_len;
        env->log.score += env->ep_return;
        env->log.r_milestone += extra[0];
        env->log.r_faction_favor += extra[1];
        env->log.milestones_reached += extra[2];
        env->log.term_success += extra[3];
        env->log.term_failure += extra[4];
        env->log.term_timer += extra[5];
        env->log.frac_combat += extra[6];
        env->log.frac_dialogue += extra[7];
        env->log.frac_overworld += extra[8];
        env->log.frac_levelup += extra[9];
        env->log.n += 1;
        env->ep_return = 0;
        env->ep_len = 0;
    }
}

void c_close(Tyranny* env) {
    if (env->sockfd > 0) {
#ifdef _WIN32
        closesocket(env->sockfd);
        WSACleanup();
#else
        close(env->sockfd);
#endif
        env->sockfd = 0;
    }
}

void c_render(Tyranny* env) { (void)env; }
