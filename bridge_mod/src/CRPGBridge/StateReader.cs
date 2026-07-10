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
            };

            s["conversation"] = ReadConversation();
            s["party"] = ReadParty();
            s["reputation"] = ReadReputation();
            return s;
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
