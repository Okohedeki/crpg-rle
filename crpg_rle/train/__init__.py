"""Training scaffolding for the CRPG RL environment.

Standalone PyTorch actor-critic + PPO and GRPO trainers that drive the Gymnasium
CRPGEnv (or a fast proxy with identical spaces) so a single-agent run can be
launched and its loss watched. This is the agent/training side, kept out of the
generic env core.
"""
