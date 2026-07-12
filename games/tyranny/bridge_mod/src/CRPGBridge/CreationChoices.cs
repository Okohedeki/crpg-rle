using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CRPGBridge
{
    /// <summary>
    /// Structured choices for character creation (incl. Conquest). One list op +
    /// one choose op covering, in priority order:
    ///   1. an open UIMessageBox (its buttons),
    ///   2. an open Conquest conflict prompt (its phase's resolutions),
    ///   3. selectable Conquest map locations,
    ///   4. the current build stage's UICharacterCreationEnumSetter options.
    /// Choosing invokes the same code paths the real UI click would, so the game
    /// validates and applies everything itself — no cursor geometry involved.
    /// </summary>
    public static class CreationChoices
    {
        // ------------------------------------------------------- enumeration
        private static UIMessageBox ActiveMessageBox()
        {
            // Only a box with a visible button is really showing; the engine keeps
            // a pooled UIMessageBox that reads active but has no buttons and would
            // otherwise mask the Conquest options.
            foreach (var b in Object.FindObjectsOfType<UIMessageBox>())
            {
                if (b == null || !b.gameObject.activeInHierarchy) continue;
                bool hasButton = false;
                if (b.Buttons != null)
                    foreach (var btn in b.Buttons)
                        if (btn != null && btn.gameObject.activeInHierarchy) { hasButton = true; break; }
                if (hasButton) return b;
            }
            return null;
        }

        private static UIConquestConflictPrompt ActivePrompt()
        {
            foreach (var p in Object.FindObjectsOfType<UIConquestConflictPrompt>())
                if (p != null && p.gameObject.activeInHierarchy && p.Conflict != null) return p;
            return null;
        }

        private static List<Game.ConquestLocation> SelectableLocations()
        {
            var list = new List<Game.ConquestLocation>();
            foreach (var loc in Object.FindObjectsOfType<Game.ConquestLocation>())
            {
                bool ok = false;
                try { ok = loc.Selectable; } catch { }
                if (ok) list.Add(loc);
            }
            list.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
            return list;
        }

        private static List<UICharacterCreationEnumSetter> EnumSetters()
        {
            var setters = new List<UICharacterCreationEnumSetter>();
            foreach (var s in Object.FindObjectsOfType<UICharacterCreationEnumSetter>())
                if (s != null && s.gameObject.activeInHierarchy) setters.Add(s);
            setters.Sort((a, b) =>
            {
                Vector3 pa = a.transform.position, pb = b.transform.position;
                int byY = pb.y.CompareTo(pa.y);
                return byY != 0 ? byY : pa.x.CompareTo(pb.x);
            });
            return setters;
        }

        private static object[] Resolutions(UIConquestConflictPrompt prompt)
        {
            try
            {
                var phase = prompt.Conflict.CurrentPhase;
                return phase != null ? phase.Resolutions : null;
            }
            catch { return null; }
        }

        private static string LabelOf(Component c)
        {
            var label = c.GetComponentInChildren<UILabel>();
            return label != null && !string.IsNullOrEmpty(label.text) ? label.text : c.gameObject.name;
        }

        public static JObject ListOptions()
        {
            var arr = new JArray();
            string kind = "none";

            var box = ActiveMessageBox();
            var prompt = ActivePrompt();
            if (box != null)
            {
                kind = "messagebox";
                for (int i = 0; i < box.Buttons.Length; i++)
                    if (box.Buttons[i] != null && box.Buttons[i].gameObject.activeInHierarchy)
                        arr.Add(new JObject { ["i"] = i, ["type"] = "BUTTON", ["label"] = LabelOf(box.Buttons[i]) });
            }
            else if (prompt != null && Resolutions(prompt) != null && Resolutions(prompt).Length > 0)
            {
                kind = "conflict";
                var res = Resolutions(prompt);
                for (int i = 0; i < res.Length; i++)
                {
                    string name = res[i] != null ? ((Object)res[i]).name : "<null>";
                    arr.Add(new JObject { ["i"] = i, ["type"] = "RESOLUTION", ["label"] = name });
                }
            }
            else
            {
                var locs = SelectableLocations();
                if (locs.Count > 0)
                {
                    kind = "location";
                    for (int i = 0; i < locs.Count; i++)
                        arr.Add(new JObject { ["i"] = i, ["type"] = "LOCATION", ["label"] = locs[i].name });
                }
                else
                {
                    var setters = EnumSetters();
                    if (setters.Count > 0)
                    {
                        kind = "build";
                        for (int i = 0; i < setters.Count; i++)
                            arr.Add(new JObject { ["i"] = i, ["type"] = setters[i].SetType.ToString(), ["label"] = LabelOf(setters[i]) });
                    }
                }
            }

            var result = new JObject { ["kind"] = kind, ["options"] = arr };
            var mgr = UICharacterCreationManager.Instance;
            if (mgr != null) { result["stage"] = mgr.CurrentStage; }
            return result;
        }

        public static JObject Choose(int index)
        {
            var box = ActiveMessageBox();
            if (box != null)
            {
                string method = index <= 0 ? "OnButton1" : "OnButton2";
                MethodInfo m = AccessTools.Method(typeof(UIMessageBox), method);
                if (m == null) return Err("messagebox handler missing");
                m.Invoke(box, new object[] { null });
                return Ok("messagebox:" + method);
            }

            var prompt = ActivePrompt();
            var res = prompt != null ? Resolutions(prompt) : null;
            if (res != null && res.Length > 0)
            {
                if (index < 0 || index >= res.Length) return Err("resolution index out of range");
                var setter = AccessTools.PropertySetter(typeof(UIConquestConflictPrompt), "Resolution");
                if (setter == null) return Err("Resolution setter missing");
                setter.Invoke(prompt, new object[] { res[index] });
                MethodInfo accept = AccessTools.Method(typeof(UIConquestConflictPrompt), "OnAcceptClicked");
                if (accept != null) accept.Invoke(prompt, new object[] { null });
                return Ok("resolution:" + ((Object)res[index]).name);
            }

            var locs = SelectableLocations();
            if (locs.Count > 0)
            {
                if (index < 0 || index >= locs.Count) return Err("location index out of range");
                Game.ConquestManager.Instance.SelectLocation(locs[index]);
                return Ok("location:" + locs[index].name);
            }

            var setters = EnumSetters();
            if (setters.Count == 0) return Err("no options available");
            if (index < 0 || index >= setters.Count) return Err("option index out of range");
            setters[index].Set();
            return Ok("build:" + setters[index].SetType);
        }

        private static JObject Ok(string what) { return new JObject { ["chosen"] = what }; }
        private static JObject Err(string e) { return new JObject { ["ok"] = false, ["error"] = e }; }
    }
}
