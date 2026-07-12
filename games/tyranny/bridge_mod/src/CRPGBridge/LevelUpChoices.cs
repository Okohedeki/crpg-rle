using System.Reflection;
using HarmonyLib;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CRPGBridge
{
    /// <summary>
    /// Structured level-up choices, the mid-game sibling of CreationChoices.
    /// Tyranny's level-up REUSES the character-creation UI: clicking a portrait's
    /// level-up icon calls UICharacterCreationManager.OpenCharacterCreation(member,
    /// 0, level+1, exp) (see UIPartyPortraitIcon.OnLevelUpClick), gated on
    /// !InCombat. So the same UICharacterCreationEnumSetter path CreationChoices
    /// drives applies here, plus a skill branch over UICharacterCreationSkillSetter.
    /// The env drives these ops from the predefined level-up plan; the agent never
    /// touches them (it only emits raw input via `act`).
    /// </summary>
    public static class LevelUpChoices
    {
        /// <summary>levelup_begin {slot}: open the level-up UI for a party member,
        /// exactly as the portrait icon does.</summary>
        public static JObject Begin(int slot)
        {
            if (SDK.GameState.InCombat) return Err("cannot level up in combat");
            SDK.PartyMemberAI[] pm = SDK.PartyMemberAI.PartyMembers;
            if (pm == null || slot < 0 || slot >= pm.Length || pm[slot] == null)
                return Err("no party member at slot " + slot);
            var member = pm[slot];
            var cs = member.gameObject.GetComponent<Game.CharacterStats>();
            if (cs == null) return Err("no CharacterStats");
            var mgr = UICharacterCreationManager.Instance;
            if (mgr == null) return Err("no UICharacterCreationManager");
            mgr.OpenCharacterCreation(member.gameObject, 0, cs.Level + 1, cs.Experience);
            return new JObject
            {
                ["open"] = UICharacterCreationManager.Instance != null,
                ["stage"] = mgr.CurrentStage,
                ["target_level"] = cs.Level + 1
            };
        }

        /// <summary>levelup_options: the current stage's selectable options (enum
        /// options via CreationChoices) plus the active skill-increment widgets.</summary>
        public static JObject ListOptions()
        {
            JObject result = CreationChoices.ListOptions();

            var skills = new JArray();
            foreach (var s in Object.FindObjectsOfType<UICharacterCreationSkillSetter>())
            {
                if (s == null || !s.gameObject.activeInHierarchy) continue;
                skills.Add(new JObject
                {
                    ["skill"] = s.Skill.ToString(),
                    ["adjustment"] = s.Adjustment
                });
            }
            result["skills"] = skills;

            var mgr = UICharacterCreationManager.Instance;
            if (mgr != null)
            {
                try
                {
                    object ch = mgr.PaperdollCharacterInfo;
                    var spt = ch.GetType().GetProperty("SkillPointsToSpend");
                    if (spt != null) result["skill_points"] = (int)spt.GetValue(ch, null);
                }
                catch { }
            }
            return result;
        }

        /// <summary>levelup_choose {index}: pick an enum/messagebox/conquest option
        /// (delegates to the shared CreationChoices path).</summary>
        public static JObject Choose(int index)
        {
            return CreationChoices.Choose(index);
        }

        /// <summary>levelup_skill {skill, delta}: apply skill-point deltas through
        /// the real UICharacterCreationSkillSetter (its own IncAllowed/point budget
        /// gates each step). delta&gt;0 increments, delta&lt;0 decrements.</summary>
        public static JObject ApplySkill(string skillName, int delta)
        {
            bool inc = delta >= 0;
            int steps = Mathf.Abs(delta);
            var onClick = AccessTools.Method(typeof(UICharacterCreationSkillSetter), "OnClick");
            if (onClick == null) return Err("SkillSetter.OnClick missing");

            var setters = Object.FindObjectsOfType<UICharacterCreationSkillSetter>();
            int applied = 0;
            for (int k = 0; k < steps; k++)
            {
                UICharacterCreationSkillSetter target = null;
                foreach (var s in setters)
                {
                    if (s == null || !s.gameObject.activeInHierarchy) continue;
                    if (s.Skill.ToString() != skillName) continue;
                    if ((s.Adjustment > 0) != inc) continue;
                    target = s;
                    break;
                }
                if (target == null) break;
                onClick.Invoke(target, null);   // gated internally; no-op if disallowed
                applied++;
            }
            return new JObject { ["skill"] = skillName, ["applied"] = applied, ["requested"] = delta };
        }

        /// <summary>levelup_advance {action}: advance/regress/complete the level-up
        /// wizard via the validated Next/Back buttons.
        /// PLAYTEST: confirm "complete" (PressOkay on the last stage) finalizes via
        /// CloseCharacterCreationOnComplete rather than the initial-creation finish.</summary>
        public static JObject Advance(string action)
        {
            var mgr = UICharacterCreationManager.Instance;
            if (mgr == null) return Err("no UICharacterCreationManager");
            int stageBefore = mgr.CurrentStage;
            switch (action)
            {
                case "advance":
                case "complete":
                    mgr.PressOkay();
                    break;
                case "regress":
                    mgr.PressBack();
                    break;
                default:
                    return Err("unknown action: " + action);
            }
            bool open = UICharacterCreationManager.Instance != null;
            var result = new JObject { ["open"] = open, ["stage_before"] = stageBefore };
            if (open) result["stage"] = UICharacterCreationManager.Instance.CurrentStage;
            return result;
        }

        private static JObject Err(string e) { return new JObject { ["ok"] = false, ["error"] = e }; }
    }
}
