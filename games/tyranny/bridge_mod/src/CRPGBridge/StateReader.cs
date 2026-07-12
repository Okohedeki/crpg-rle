using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CRPGBridge
{
    /// <summary>
    /// Snapshots engine state into the observe payload. Main-thread only
    /// (called from the IPC pump). Every accessor is defensive: most engine
    /// singletons are null at the main menu.
    /// </summary>
    public static class StateReader
    {
        // Factions surfaced in every snapshot. FactionName is int-backed;
        // ids verified against the decompiled enum.
        private static readonly int[] TrackedFactions =
        {
            (int)FactionName.ScarletChorus,
            (int)FactionName.Disfavored,
            (int)FactionName.SK_Tunon,
            (int)FactionName.SK_GravenAshe,
            (int)FactionName.SK_VoicesSoldak,
            (int)FactionName.SK_BledenMark,
        };

        public static JObject Snapshot()
        {
            var s = new JObject
            {
                ["frame"] = Time.frameCount,
                ["time_scale"] = Time.timeScale,
                ["loading"] = SDK.GameState.IsLoading,
                ["in_combat"] = SDK.GameState.InCombat,
                ["game_over"] = SDK.GameState.GameOver,
                ["party_dead"] = SDK.GameState.PartyDead,
                ["paused"] = SafePaused(),
                ["area"] = SDK.GameState.LoadedLevelName ?? "",
                ["in_creation"] = InCreation(),
                ["cheats"] = SDK.GameState.CheatsEnabled,
                ["player_dead"] = PlayerDead(),
                ["player_on_screen"] = PlayerOnScreen(),
            };

            s["conversation"] = ReadConversation();
            s["party"] = ReadParty();
            s["reputation"] = ReadReputation();
            s["creation"] = ReadCreation();

            var levelUp = ReadLevelUp();
            s["level_up_detail"] = levelUp;
            // Top-level flag mode_detect reads. Suppress during combat/loading:
            // OpenCharacterCreation (the level-up UI) is gated on !InCombat and the
            // scripted level-up trigger must not fire mid-fight.
            s["level_up"] = levelUp["pending"].Value<bool>()
                && !SDK.GameState.InCombat && !SDK.GameState.IsLoading;
            return s;
        }

        /// <summary>Any party member with a bankable level or unspent points.
        /// Level-up reuses the creation UI (UICharacterCreationManager); the
        /// scripted config-driver applies the predefined plan when this is set.</summary>
        private static JObject ReadLevelUp()
        {
            var r = new JObject { ["pending"] = false };
            var members = new JArray();
            bool anyPending = false;
            try
            {
                SDK.PartyMemberAI[] pm = SDK.PartyMemberAI.PartyMembers;
                if (pm != null)
                {
                    for (int slot = 0; slot < pm.Length; slot++)
                    {
                        SDK.PartyMemberAI m = pm[slot];
                        if (m == null) continue;
                        var cs = m.gameObject.GetComponent<Game.CharacterStats>();
                        if (cs == null) continue;
                        bool avail = false, unspent = false;
                        try { avail = cs.LevelUpAvailable(); } catch { }
                        try { unspent = cs.UnusedPoints(); } catch { }
                        if (!avail && !unspent) continue;
                        anyPending = true;
                        int maxLevel = cs.Level;
                        try { maxLevel = cs.GetMaxLevelCanLevelUpTo(); } catch { }
                        members.Add(new JObject
                        {
                            ["slot"] = slot,
                            ["name"] = m.gameObject.name,
                            ["level"] = cs.Level,
                            ["max_level"] = maxLevel,
                            ["unspent"] = unspent
                        });
                    }
                }
            }
            catch { /* party not alive (main menu / creation) */ }
            r["pending"] = anyPending;
            r["members"] = members;
            bool uiOpen = false;
            try { uiOpen = UICharacterCreationManager.Instance != null; } catch { }
            r["ui_open"] = uiOpen;
            return r;
        }

        private static JObject ReadCreation()
        {
            var r = new JObject { ["active"] = false };
            try
            {
                var mgr = UICharacterCreationManager.Instance;
                if (mgr == null) return r;
                r["active"] = true;
                r["stage"] = mgr.CurrentStage;
                r["last_stage"] = mgr.LastStage;
                try { r["ready"] = mgr.IsCharacterCreationReadyForCompletion(); }
                catch { r["ready"] = false; }
            }
            catch { }
            return r;
        }

        private static bool SafePaused()
        {
            try { return SDK.GameState.Paused; }
            catch { return false; } // TimeController not alive yet
        }

        private static bool InCreation()
        {
            try { return UICharacterCreationManager.Instance != null; }
            catch { return false; }
        }

        /// <summary>Whether the player character is inside the visible viewport.
        /// The agent interacts by clicking what it sees, so the env penalizes
        /// steps where the MC has been scrolled off-screen. Defaults to true
        /// when there is no player/camera (menus, loading, creation).</summary>
        private static bool PlayerOnScreen()
        {
            try
            {
                var pc = SDK.GameState.s_playerCharacter;
                if (pc == null) return true;
                Camera cam = Camera.main;
                if (cam == null) return true;
                Vector3 vp = cam.WorldToViewportPoint(pc.transform.position);
                // This engine's world camera is orthographic; on this Unity the
                // projected z sign is unreliable for ortho, so only gate on z for
                // perspective cameras.
                bool inFront = cam.orthographic || vp.z > 0f;
                return inFront && vp.x >= 0f && vp.x <= 1f && vp.y >= 0f && vp.y <= 1f;
            }
            catch { return true; }
        }

        /// <summary>Whether the main character (player) is dead — the signal for
        /// the deathless-MC reward. MC death is game-over in Tyranny.</summary>
        private static bool PlayerDead()
        {
            try
            {
                var pc = SDK.GameState.s_playerCharacter;
                if (pc == null) return false;
                var health = pc.GetComponent<Game.Health>();
                return health != null && health.Dead;
            }
            catch { return false; }
        }

        private static JObject ReadConversation()
        {
            var result = new JObject { ["active"] = false };
            try
            {
                ConversationManager cm = ConversationManager.Instance;
                if (cm == null) return result;
                FlowChartPlayer player = cm.GetActiveConversationForHUD();
                if (player == null) return result;

                var conv = player.CurrentFlowChart as Conversation;
                result["active"] = true;
                result["file"] = conv != null ? (conv.Filename ?? "") : "";
                result["node"] = player.CurrentNodeID;

                var options = new JArray();
                if (conv != null)
                {
                    var nodes = conv.GetResponseNodes(player);
                    if (nodes != null)
                    {
                        for (int i = 0; i < nodes.Count; i++)
                        {
                            string text = conv.GetNodeText(player, nodes[i], true);
                            options.Add(new JObject
                            {
                                ["i"] = i,
                                ["node"] = nodes[i].NodeID,
                                ["text"] = text ?? ""
                            });
                        }
                    }
                }
                result["options"] = options;
            }
            catch (Exception ex)
            {
                result["error"] = ex.GetType().Name + ": " + ex.Message;
            }
            return result;
        }

        private static JArray ReadParty()
        {
            var party = new JArray();
            try
            {
                SDK.PartyMemberAI[] members = SDK.PartyMemberAI.PartyMembers;
                if (members == null) return party;
                for (int slot = 0; slot < members.Length; slot++)
                {
                    SDK.PartyMemberAI m = members[slot];
                    if (m == null) continue;
                    var entry = new JObject { ["slot"] = slot, ["selected"] = m.Selected };
                    Vector3 pos = m.transform.position;
                    entry["pos"] = new JArray(pos.x, pos.y, pos.z);

                    var health = m.gameObject.GetComponent<Game.Health>();
                    if (health != null)
                    {
                        entry["hp"] = health.CurrentHealth;
                        entry["max_hp"] = health.MaxHealth;
                        entry["dead"] = health.Dead;
                    }
                    party.Add(entry);
                }
            }
            catch (Exception)
            {
                // party not alive (main menu / creation)
            }
            return party;
        }

        private static JObject ReadReputation()
        {
            var reps = new JObject();
            try
            {
                var rm = Game.ReputationManager.Instance;
                if (rm == null) return reps;
                foreach (int id in TrackedFactions)
                {
                    var rep = rm.GetReputation(id, true);
                    if (rep == null) continue;
                    reps[((FactionName)id).ToString()] = new JObject
                    {
                        ["favor"] = rep.PositiveAxisValue,
                        ["wrath"] = rep.NegativeAxisValue,
                        ["favor_rank"] = rep.GoodRank,
                        ["wrath_rank"] = rep.BadRank
                    };
                }
            }
            catch (Exception)
            {
                // reputation system not alive yet
            }
            return reps;
        }
    }
}
