# Tyranny Decompile Notes — Harmony Hook Reference

Sources:
- `H:\RL\tools\extracted\assembly_csharp\` — ILSpy decompile of `Assembly-CSharp.dll` (1147 .cs): `Game.*` subclasses + global-namespace `UI*` classes.
- `H:\RL\tools\extracted\assembly_csharp_firstpass\` — ILSpy decompile of `Assembly-CSharp-firstpass.dll` (895 .cs): the engine/SDK layer. **All previously-inferred signatures below are now verified against this source** and marked **[verified]** with file refs.

Game: Tyranny (Obsidian 2016), Unity 5.4 Mono, OEI/PoE1 shared engine. NGUI UI.

## ARCHITECTURE + NAMESPACE MAP (verified — important correction)

Three layers:
1. `Assembly-CSharp.dll` → `Game.*` namespace subclasses (`Game.GameState : SDK.GameState`, etc.) + global-namespace UI classes.
2. `Assembly-CSharp-firstpass.dll` → the engine layer. **Namespace split inside firstpass:**
   - **`namespace SDK`** (files in `SDK/`): `SDK.GameState`, `SDK.GameResources`, `SDK.CommandLine`, `SDK.Reputation`, `SDK.ReputationManager`, `SDK.QuestManager`, `SDK.PartyMemberAI`, `SDK.Health`, `SDK.CharacterStats`, `SDK.GameCursor`, `SDK.WorldTime`.
   - **GLOBAL namespace** (files at firstpass root — my earlier notes wrongly called these `SDK.*`): `GameInput`, `GlobalVariables`, `TimeController`, `Console`, `Conversation`, `ConversationManager`, `FlowChart`, `FlowChartPlayer`, `SaveGameInfo`, `PersistenceManager`, etc. For `AccessTools.TypeByName` use the bare name, e.g. `"GameInput"`, `"TimeController"`, `"ConversationManager"` — NOT `"SDK.GameInput"`.
3. `OEIFormats.dll` (STILL not decompiled): `OEIFormats.FlowCharts.*` node data classes — `FlowChartNode`, `PlayerResponseNode`, `DialogueNode`, `ScriptNode`, `BankNode`, `FlowChartLink`, quest `ObjectiveNode`. Member names below for these are from call-sites only (still reliable; decompile OEIFormats.dll if exact overloads needed).

---

## 1. GameState — `Game/GameState.cs` [HERE] : `SDK.GameState` (`firstpass/SDK/GameState.cs`) [verified]

`public abstract class SDK.GameState : MonoBehaviour`; `public class Game.GameState : SDK.GameState`.

**Singleton / player [verified]:**
```csharp
public static SDK.GameState Instance => s_instance;                 // SDK/GameState.cs L134 (protected static s_instance)
public new static Game.GameState Instance => SDK.GameState.s_instance as Game.GameState;   // Game layer
public static Player SDK.GameState.s_playerCharacter;               // L24 — public static field, type Player
public static Faction SDK.GameState.s_playerCharacterFaction;       // L26
public static ControlMapping SDK.GameState.Controls;                // L32 — key bindings
public static event EventHandler PlayerCharacterChanged;            // Game layer
```

**Combat [verified, SDK/GameState.cs]:**
```csharp
public static bool InCombat => s_isInCombat;         // L136 (s_isInCombat: protected static bool)
public static event EventHandler CombatStart;        // L162  <-- subscribe (NOT "OnCombatStart" — that's the internal raiser)
public static event EventHandler CombatEnd;          // L164
// Game layer: CannotSaveBecauseInCombat, IsInTrapTriggeredCombat, InCombatDuration, ForceCombatMode { get; set; }
// combat detection loop: Game.GameState.UpdateIsInCombatAndGameOver() runs every Update()
```

**Paused [verified]:** `public static bool Paused { get; }` (L150) — **delegates to `TimeController.Instance.Paused`** (which is `Time.timeScale == 0f`). Read-only here; write via TimeController (§7).

**Map / area:** Game layer `GetCurrentMap()/SetCurrentMap/GetLastMap/CurrentRegion/GetCurrentMapName()` [HERE]. SDK statics [verified]: `LoadedLevelName => SceneManager.GetActiveScene().name` (L132), `ApplicationLoadedLevelName { get; set; }` (L130), `CurrentSceneIsTransitionScene()` (scene `"oei_scene_transition"`).

**Game over / death [verified]:**
```csharp
public static bool GameOver { get { return s_gameOver; } set { s_gameOver = value; } }   // L138
public static bool PartyDead { get; set; }                                                // L109
```
On game over `UIDeathManager.Instance.ShowWindow()` fires ~2s after PartyDead [HERE].

**Loading [verified]:**
```csharp
public static bool IsLoading { get; set; }                          // L65
public static bool IsTransitionInProgress => IsLoading || s_firstLoad;   // L67
public static bool IsRestoredLevel { get; set; }  LoadedGame { get; set; }  NewGame { get; set; }   // L63/69/71
public static string LoadedFileName { get; set; }  public static SaveGameInfo LoadedSaveGameInfo { get; set; }  // L102/104
public static event EventHandler LevelUnload;         // L166
public static event EventHandler LevelLoadedEarly;    // L168
public static event EventHandler LevelLoaded;         // L170
public static event EventHandler LevelLoadedLate;     // L172
public static event EventHandler Resting;             // L174
// Game layer: FinalizeLevelLoad() fires the LevelLoaded* events then sets IsLoading=false — postfix = "load complete"
```
Also [verified]: `public static bool CheatsEnabled { get; set; }` (L78 — needed for console cheats), `PlayerSafeMode` (L107), `FirstPlaythrough`, `GameComplete`, `NumSceneLoads`, `public Guid PlaythroughGUID { get; set; }` (instance, L118).

**Scene helpers [HERE]:** `LoadMainMenu(bool)`, `ChangeLevel(MapData/MapType/string)`, `LoadLevel(MapData/string)`, `BeginLevelUnload(string)`, `Autosave()`, `EndGameAndLoadCredits()`, `ReturnToMainMenuFromError()` (`public virtual` on SDK base L432). `public static GameMode Mode;` / `Option => Mode` [HERE]. Difficulty/TrialOfIron/ExpertMode persistent props [HERE].

**Verdict:** read via SDK statics; subscribe `SDK.GameState.CombatStart/CombatEnd/LevelLoaded` **events** (correct names verified); postfix `Game.GameState.FinalizeLevelLoad` for load-done.

---

## 2. Conversation system — `Conversation.cs`, `ConversationManager.cs`, `FlowChart.cs`, `FlowChartPlayer.cs` (all firstpass root, GLOBAL namespace) [verified]

### ConversationManager (`firstpass/ConversationManager.cs`) : MonoBehaviour [verified]
```csharp
public static ConversationManager Instance => s_instance;                                  // L40
public delegate void FlowChartPlayerDelegate(FlowChartPlayer chartPlayer);                 // L13
public FlowChartPlayerDelegate FlowChartPlayerAdded;    // L21 — public FIELD (not event); Game code Delegate.Combine's into it
public FlowChartPlayerDelegate FlowChartPlayerRemoved;  // L23
public FlowChartPlayer GetActiveConversationForHUD();                                      // L360
public FlowChartPlayer StartConversation(string conversationFilename, GameObject owner, FlowChartPlayer.DisplayMode displayMode, bool disableVo = false);          // L205 — programmatic convo start
public FlowChartPlayer StartConversation(string conversationFilename, int startNode, GameObject owner, FlowChartPlayer.DisplayMode displayMode, bool disableVo = false);  // L210
public void EndConversation(FlowChartPlayer player, bool triggerScripts = true);           // L301
public bool IsConversationActive(FlowChartPlayer);  public bool IsConversationOrSIRunning();  // L351/374
public static bool IsWMEConversation(FlowChartPlayer player);                              // L248
public void SetNodeCompleted(Conversation convo, int nodeID, bool complete);  bool GetNodeCompleted(Conversation, int);   // L392/397
public void SetMarkedAsRead(Conversation, int nodeID);  bool GetMarkedAsRead(Conversation, int nodeID);  // L434/463
public List<string> FindConversations(string search);                                      // L42
public static string FormatConversationFilename(string filename);                          // L140
public FlowChartPlayer StartScriptedInteraction(string conversationFilename, GameObject owner);   // L296
```

### FlowChartPlayer (`firstpass/FlowChartPlayer.cs`) — plain class [verified, whole file]
```csharp
public enum DisplayMode { Standard, Cutscene, Interaction }
public int StartNodeID { get; set; }   public int CurrentNodeID { get; set; }     // current node id
public FlowChart CurrentFlowChart { get; set; }   public GameObject OwnerObject { get; set; }
public DisplayMode FlowChartDisplayMode { get; set; }   public bool FadeFromBlackOnExit { get; set; }
public bool Completed { get; private set; }   public void SetComplete();   public bool DisableVO { get; set; }
```

### FlowChart (`firstpass/FlowChart.cs`) : ScriptableObject [verified]
```csharp
public void MoveToNode(int nodeID, FlowChartPlayer player);            // L69  <-- ADVANCE
public void MoveToPreviousNode(FlowChartPlayer player);                // L127
public FlowChartNode GetNode(int nodeID);                              // L141
public FlowChartNode GetNextNode(FlowChartPlayer player);              // L230 (public; the List<FlowChartLink> overload is protected virtual)
public List<FlowChartNode> GetAllNodesFromActiveNode(FlowChartPlayer player);   // L196
public virtual void StartFlowChart(FlowChartPlayer player);  public void UpdateFlowChart(FlowChartPlayer player);
public virtual string Filename { get; set; }   public const int INVALID_NODE_ID = -1;
protected virtual bool PassesConditionals(FlowChartNode node, FlowChartPlayer player);   // L338
```

### Conversation (`firstpass/Conversation.cs`) : FlowChart [verified]
```csharp
public enum NodeTextRequestType { Unspecified, PassingOnly, FailingOnly }                  // L14
public static bool LocalizationDebuggingEnabled { get; set; }                              // L33
public List<PlayerResponseNode> GetResponseNodes(FlowChartPlayer player);                  // L885  <-- response enumeration
public List<PlayerResponseNode> GetResponseNodes(FlowChartPlayer player, bool qualifiedOnly);   // L890
public string GetActiveNodeText(FlowChartPlayer player);                                   // L417
public string GetActiveNodeRawText(FlowChartPlayer player);                                // L434
public string GetNodeText(FlowChartPlayer player, FlowChartNode node, bool forPlayerInput, NodeTextRequestType requestType = NodeTextRequestType.Unspecified);   // L600  <-- TEXT RESOLUTION (patch to swap)
public string GetNodeQualifier(FlowChartNode node, FlowChartPlayer player);                // L451
public List<NodeQualifierBase> GetNodeQualifiersHelper(FlowChartNode node, FlowChartPlayer player, bool checkpassing, bool passing, bool firstonly, bool forDisplayPurposes);  // L472
public bool PassesConditionalsEx(FlowChartNode node, FlowChartPlayer player);              // L829 (param type is FlowChartNode — PlayerResponseNode derives from it)
public GameObject GetSpeaker(int nodeId);  GetSpeaker(FlowChartNode node);                 // L1042/1047 (instance)
public static GameObject GetSpeaker(FlowChartPlayer player);                               // L1118 (static)
public static void ClearSpeakerGUIDCache();                                                // L1113
public void PlayVO(FlowChartNode currentNode, FlowChartPlayer player);  StopVO(int nodeID);  float GetVODuration(int nodeID);
```
Node data classes (`FlowChartNode.NodeID/.NodeType/.Links/.ClassExtender`, `PlayerResponseNode.Persistence/.Conditionals`, `DialogueNode.HideSpeaker`) are in **OEIFormats.dll** (not decompiled) — usage-derived. Display text resolution goes through the flowchart's StringTable inside `GetNodeText`; returned string is already localized. `int nodeID` → VO via `GameResources.GetVOAssetForConversation(dialogueName, nodeID, useFemale)` [HERE].

**Verdict [verified]:** postfix `Conversation.GetNodeText` (note 4th default param `NodeTextRequestType`) for text swap; postfix `Conversation.GetResponseNodes(FlowChartPlayer)` AND the 2-arg overload for order shuffle — both called by the UI each rebuild. `ConversationManager.Instance.StartConversation(...)` starts conversations programmatically. Pick response i = `flowchart.MoveToNode(responseNodes[i].NodeID, player)` (see §3 for the cleaner UI-level entry).

---

## 3. Dialogue UI — `UIConversationManager.cs` [HERE, Assembly-CSharp] (verified against firstpass types)

Singleton `UIConversationManager.Instance` (private `s_Instance`). Fields: `m_ActiveFlowChart` (FlowChartPlayer), `m_CurrentNodeId` (int), `ConversationTextList` (UIConsoleText, UILabel-backed), `ContinueButton`/`ContinueButtonLabel`.
```csharp
private int DrawResponses();                       // builds numbered response list from GetResponseNodes + GetNodeText, TextList.Add(...)
private int DrawResponsesDebug();                  // localization-debug variant
public void CheckRecreateContent();                // per-frame rebuild driver (Update, on node change or ForceRefresh)
public override void HandleInput();                // input router:
   int line = TextList.LineAt(GameInput.MousePosition);  int idx = LineToResponse(line);   // private int LineToResponse(int) => m_OutstandingResponses - TextList.ParagraphCount + line
   if (GameInput.NumberPressed > 0) PlayerKeyInput(GameInput.NumberPressed - 1);   // Alpha1..9 → idx 0..8 (NumberPressed == -1 when none — verified §9)
   GameInput.GetMouseButtonDown/Up(0, setHandled:true) → PlayerKeyInput(idx)
   GameInput.GetControlDown/Up(MappedControl.CONV_CONTINUE) → continue button
private void PlayerKeyInput(int number);           // dispatch
private void PlayerInput(int number);              // <-- THE pick-response(i) method (0-based into GetResponseNodes list);
                                                   //     validates PassesConditionalsEx, MoveToNode(responseNodes[number].NodeID)
public static bool IsInConversation();
public bool HasConversationNodeBeenCompletedAlready();
```
**Verdict:** postfix `PlayerInput(int)` to observe the chosen index; invoke it (reflection) to choose programmatically. Text/order hooks live at the Conversation level (§2). `IsInConversation()` is the gate.

---

## 4. Reputation / factions — `SDK/Reputation.cs`, `SDK/ReputationManager.cs` [verified] + Game layer [HERE]

`FactionName` enum [HERE, Assembly-CSharp/FactionName.cs], int-backed, 117 values: `None=0, ScarletChorus=1, Disfavored=2, Comp_*=3..11, Rebel_*=12..17, MageGuild_*=18..23, SK_Tunon=24, SK_GravenAshe=25, SK_VoicesSoldak=26, SK_BledenMark=27, Art_*=28.., Skirmish_Ally=40, Skirmish_Enemy=41(engine remaps 39/40 during skirmish), Player=64, ...`. `(int)FactionName.X` = reputation id.

**SDK.Reputation [verified, firstpass/SDK/Reputation.cs]:**
```csharp
public enum ChangeStrength { None, VeryMinor, Minor, Average, Major, VeryMajor }   // L10
public enum Axis { Positive, Negative }    public enum RankType { ... }            // L20/26
public static int MaxRank = 5;                                                     // L34 — public static FIELD
public int PositiveAxisValue { get; set; }   // L188 — raw Favor points
public int NegativeAxisValue { get; set; }   // L201 — raw Wrath points
public int GoodRank { get; }   public int BadRank { get; }                          // L80/90
public int GetRank(out RankType rankType);   public int GetAxisRank(Axis axis);     // L448/443
public float GetReputationPct(Axis axis);    public int GetScaleForAxis(Axis axis); // L393/403
public int PctToRank(float pct);   public string GetAxisDisplayName(Axis axisType); // L428/268
public virtual void AddReputation(Axis axis, ChangeStrength strength);              // L262
protected virtual void AddReputation(Axis axis, int amount);                        // L277 (int overload is protected)
public virtual void RemoveReputation(Axis axis, ChangeStrength strength);  protected virtual void RemoveReputation(Axis axis, int amount);  // L330/336
public virtual bool CanAddReputation(Axis, ChangeStrength) / (Axis, int);  CanRemoveReputation(...);   // L308/315/374/380
public virtual int GetPointsThatCanBeAdded(Axis axis, int amount);                  // L320
public FactionDatabaseString Name; Description; PositiveAxisName; NegativeAxisName; // fields L40-57
```
**Game.Reputation [HERE]:** `FactionID` (FactionName), `Type` (ReputationType { Faction, Companion, Artifact, Archon }), `IsFriendly()/IsHostile()`, `ForceHostile(int)`, `SetAxisRank(Axis,int,int)`, `GetMaxRank(Axis)`, `GetChangeEventsForAxis(Axis)`, ChangeEvent record class.

**Game.ReputationManager [HERE]:** singleton `ReputationManager.Instance` (`SDK.ReputationManager.s_instance as ...`), `Reputation[] Factions`, `List<FactionName> Alliance`, `event Action<Reputation> OnReputationNewAbilityChanged`, `GetReputation(int id, bool suppressWarnings=false)` [override],
**mutator hooks:** `public bool AddReputation(SDK.Reputation rep, Axis axis, ChangeStrength strength, int reasonIndex, bool ignoreLinkedReputations=false)` (+ `(int factionId, ...)` and 3-arg override overloads) and matching `RemoveReputation` overloads — postfix = favor/wrath event stream. Adds suppressed if the conversation node was already completed; Belief granted at `strength >= BeliefRepThreshold`.

**Verdict [verified]:** read `.PositiveAxisValue/.NegativeAxisValue/.GoodRank/.BadRank`; postfix the ReputationManager 5-arg mutators.

---

## 5. Quests — `SDK/QuestManager.cs` [verified] + `Game/QuestManager.cs` [HERE]

```csharp
public static QuestManager Instance => s_instance;                                 // SDK L260
public delegate void QuestDelegate(Quest quest);                                   // L197
public QuestDelegate OnQuestStarted;     // L244 — public FIELDS (not events); Delegate.Combine to subscribe
public QuestDelegate OnQuestCompleted;   // L248
public QuestDelegate OnQuestFailed;      // L250
public QuestDelegate OnQuestAdvanced;    // L256   <-- milestone stream (all four verified)
public void TriggerQuestEndState(string questName, int endStateID, bool failed);   // L1084
public void TriggerQuestEndState(Quest quest, int endStateID, bool failed);        // L1108
public void TriggerGlobalVariableEvent(string globalVariableName, int variableValue);   // L1341 — fired by GlobalVariables.SetVariable!
public List<string> FindLoadedQuests(string search);
// Game layer [HERE]: protected override CompleteQuestObjective(Quest, ObjectiveNode); CompleteQuest(Quest);
//                    public CompleteAndRemoveQuest(string/Quest); static FormatQuestName(string) on SDK base
```
Quest ids = `quest.Filename` (`OEIFormats.FlowCharts.Quests.Quest`). `base.LoadedQuests` Dictionary keyed by formatted filename; `base.QuestTrackers[filename].QuestLevel`.
**Verdict [verified]:** Delegate.Combine into `OnQuestAdvanced`/`OnQuestCompleted`/`OnQuestFailed` fields, or postfix `TriggerQuestEndState`/`CompleteQuest*`.

---

## 6. Global variables — `firstpass/GlobalVariables.cs` (GLOBAL namespace, MonoBehaviour) [verified, whole file]

```csharp
public static GlobalVariables Instance => s_instance;
public int  GetVariable(string name);        // returns -1 if key missing (NOT 0 — verified L130)
public void SetVariable(string name, int val);   // L108 — upserts Hashtable m_data, then calls
                                                 //   QuestManager.Instance.TriggerGlobalVariableEvent(name, value)  <-- built-in event fan-out
public void QueueVariable(string name, int val); // thread-safe deferred set (applied in Update)
public bool IsValid(string variableName);
public static void WriteGlobalsToSaveGame();     // writes {Application.persistentDataPath}/CurrentGame/globals.dat  (hardcoded — see §8)
public static void ReadGlobalsFromSaveGame();
public const string Difficulty = "_g_Difficulty";
```
Backing store: `[Persistent] private Hashtable m_data` (string→int, 4096 cap). Defaults loaded from `{dataPath}/data/design/globalvars/game.globalvariables`. Example keys: `"_g_Difficulty"`, `"Act1_Gameover"`, edict break vars (`Edict.HowToBreakEdictVar.Name`).
**Verdict [verified]:** postfix `SetVariable(string,int)` for the mutation stream — or skip the patch and hook `QuestManager.TriggerGlobalVariableEvent(string,int)` which SetVariable already calls. Reads return -1 for unknown keys.

---

## 7. Time — `Game/WorldTime.cs` [HERE] : `SDK.WorldTime` [verified] + `firstpass/TimeController.cs` (GLOBAL ns) [verified, whole file]

### SDK.WorldTime [verified, firstpass/SDK/WorldTime.cs]
```csharp
public static WorldTime Instance => s_instance;
public OEIDateTime CurrentTime { get; set; }   public OEIDateTime AdventureStart { get; set; }
public TimeInterval TimeInCombat { get; set; }  TimeSpentTravelling { get; set; }
public int CurrentSecond/CurrentMinute/CurrentHour { get; }   public int FrameWorldSeconds { get; protected set; }
public float RealWorldPlayTime { get; set; }   public abstract int GameSecondsPerRealSecond { get; }
```
Game layer [HERE]: `AdvanceTimeBySeconds(int[,bool isTravel,bool isResting])`, `AdvanceTimeByHours(int,bool)`, `AdvanceTimeToHour(int)`, `event WorldTimeEventHandler OnTimeJump` (`(int gameSeconds, bool isMapTravel, bool isResting)`), calendar constants (26-day months, 14-month years, HoursPerDay=24). Edict/"Day of Swords" countdown = date math on `CurrentTime` + GlobalVariables (no dedicated countdown class; cf. `AchievementTracker.TrackedAchievementStat.HasDayOfSwordsArriveWithoutTakingVedrienWell`).

### TimeController [verified — the pause/speed authority]
```csharp
public static TimeController Instance { get; private set; }
public bool ProhibitPause;                       // public field (main menu sets true)
public float NormalTime = 1f;                    // public INSTANCE FIELDS — the three speed tiers.
public float SlowTime = 0.2f;                    //   Overwrite these for arbitrary speed values!
public float FastTime = 1.8f;
private float m_TimeScale;                       // current desired scale
private float TimeScale { get; set; }            // PRIVATE property wrapping m_TimeScale (setter also stores m_resumeTime out of combat)
public bool Paused   { get { return Time.timeScale == 0f; } set /* m_PlayerPaused = value; UpdateTimeScale(prev) */ }
public bool SafePaused { get => Paused; set { if (!value || CanPause) Paused = value; } }
public bool PlayerPaused => m_PlayerPaused;   public bool UiPaused { get; set; }   public bool CanPause { get; }
public bool Slow { get => TimeScale == SlowTime; set }   public bool Fast { get => TimeScale == FastTime; set }
public void SetNormal();  ToggleSlow();  ToggleFast();
public void Flash(float speed);                  // <-- ARBITRARY MULTIPLIER API: sets TimeScale = speed (public!)
public static float FlashSpeed { get; }          // current flash scale (1f if not flashed)
public event Action<bool> PauseChanged;
public static float sUnscaledDelta => Time.unscaledDeltaTime;
private void UpdateTimeScale();                  // THE Time.timeScale writer: paused→0, cutscene→1, else TimeScale.
                                                 //   Called every Update() when !GameState.IsTransitionInProgress → stomps external writes each frame.
```
**Verdict [verified]:** For arbitrary game speed call `TimeController.Instance.Flash(x)` (public — exactly the `Flash` console cheat) or set `NormalTime`/private `m_TimeScale` via reflection. Do NOT write `Time.timeScale` directly — `UpdateTimeScale()` overwrites it every frame; if you must force a value, postfix `UpdateTimeScale` (private, no-arg) as the final authority. Pause via `Paused`/`SafePaused` setters; `PauseChanged` event for notifications. Note combat-end resets scale to `m_resumeTime` (CombatEnd subscriber).

---

## 8. Save / load — `Game/GameResources.cs` [HERE] : `SDK.GameResources` [verified] + `SaveGameInfo`/`PersistenceManager` (GLOBAL ns) [verified]

**Programmatic API [HERE, static]:** `Game.GameResources.SaveGame(string filename)` / `SaveGame(string filename, string userString, bool ShouldCloudSync=false) : bool` (returns false while `InCombat`/`IsTransitionInProgress`) and `LoadGame(string filename) : bool`; `LoadLastGame(bool fadeOut)`, `GetContinueSaveGame()`, `DeleteSavedGame(string,bool)`, `LoadSaveFile(string, SaveGameInfo.SizeStyle)`, `SaveGameExists([string])`. `Game.GameState.Autosave()` [HERE].

**Save directory seam [verified — firstpass/SDK/GameResources.cs L35-63]:**
```csharp
public static string SaveGamePath { get {
    // default: PersistentDataPath
    // Windows: Path.Combine(WindowsPathHelper.GetSaveGameDirectory(), "Tyranny")   // "Saved Games\Tyranny"
    // OSX / Linux (XDG_DATA_HOME) variants...; CREATES the dir if missing; returns it
}}
public static string PersistentDataPath => GameUtilities.FilePath_AppPersistentDataPath();   // L29
public static string TemporaryCachePath => ...;   public static string DataPath => ...;      // L33/31
public static bool SaveFileExists(string saveName);              // Path.Combine(SaveGamePath, saveName)
public static SaveGameInfo BuildSaveFile(string name, string userString);   // L211 — appends ".savegame", PersistenceManager.SaveGame(), SaveGameInfo.Save(...)
public static event LoadedSave EventPreSaveGame; EventLoadedSave; EventPreloadGame;   // L65-69 (raisers OnPreSaveGame/OnLoadedSave/OnPreloadGame)
```
**Redirect verdict [verified]:** prefix-patch the `SDK.GameResources.SaveGamePath` **static getter** (skip original, return per-instance dir) — every save/load/list path `Path.Combine`s on it. **BUT for full per-instance isolation you must ALSO handle** (verified hardcoded paths):
- `PersistenceManager.s_tempSavePath = Path.Combine(Application.persistentDataPath, "CurrentGame")` — **public static field** (firstpass/PersistenceManager.cs L15; also `s_mobileObjPath` L17 derives from it, `s_oldTempSavePath` L13). The working level/mobile-object data lives here and is SHARED between concurrent instances. Rewrite these three static fields at plugin init (before any save/load activity).
- `GlobalVariables.WriteGlobalsToSaveGame()/ReadGlobalsFromSaveGame()` hardcode `Path.Combine(Application.persistentDataPath, "CurrentGame")/globals.dat` **inline** (do not use s_tempSavePath) — patch these two statics too, or accept that globals.dat stays shared.

**SaveGameInfo [verified, firstpass/SaveGameInfo.cs]:** consts `QUICK_SAVE="quicksave.savegame"`, `AUTO_SAVE="autosave.savegame"`, `SAVE_EXTENSION=".savegame"`, `CurrentSaveVersion=5`, `SAVE_FILENAME="saveinfo.xml"`; public fields `PlayerName, MapName, SceneTitle, FileName, UserSaveName, CloudSaveGUID`; `static List<SaveGameInfo> CachedSaveGameInfo { get; }` (L174); `static event Action OnSaveCachingComplete` (L197); `static void WaitUntilSafeToSaveLoad()` (L246); `static bool IsSavingThreadAlive` (L162); `SizeStyle` enum; `.RealTimestamp`, `.Difficulty`, `.SaveVersion` (usage).

**Load-completion detection [verified]:** `SDK.GameState.IsLoading` false-edge (set in `Game.GameState.FinalizeLevelLoad`), or subscribe `SDK.GameState.LevelLoaded/LevelLoadedLate` events, or `SDK.GameResources.EventLoadedSave` (raised via `OnLoadedSave()` at the end of `Game.GameResources.LoadGame`).

**PersistenceManager [verified, firstpass/PersistenceManager.cs]:** `static void SaveGame()` (L254), `static string GetLevelFilePath(string levelName)` (L268), `LevelLoaded()` (L483), `ClearPersistenceObjects()` (L197), `MobileObjects`/`PersistentObjects` (Dictionary<Guid, ObjectPersistencePacket>), `ModifySavedValue(Guid, Type component, string variable, object newValue)` / `GetSavedValue(...)` (L75/L110 — handy for save surgery), `static event EventHandler OnLoadObjects` (L29).

---

## 9. Input — `firstpass/GameInput.cs` (GLOBAL namespace, MonoBehaviour) [verified, whole file] + `SDK.GameCursor` [verified] + NGUI `UICamera` [HERE]

### GameInput — THE world-input wrapper. All members verified:
```csharp
public static GameInput Instance { get; private set; }
public static bool DisableInput { get; set; }                        // master gate — most Get* return false when true
public static int NumberPressed => s_NumberPressed;                  // -1 when none (NOT 0). Set in Update from Alpha0-9 / Keypad0-9.
public static bool ClickHandled { set; }                             // SET-ONLY property (no getter!) — setting true calls HandleAllClicks()
public static Vector3 MousePosition => Input.mousePosition;          // passthrough — Vector3
public static Vector3 MouseDelta => Input.mousePosition - s_lastMouse;
public static Vector3 GlobalMousePosition => s_globalMousePos;       // accumulated from GetAxisRaw("Mouse X/Y")
public static Vector3 WorldMousePosition => s_pickLocation;          // world point (raycast vs "Walkable" layer, computed in Update)
public static bool WorldMousePositionOnNav => s_pickLocationOnNavMesh;
// buttons / keys (each checks DisableInput + per-frame handled arrays, then delegates to UnityEngine.Input):
public static bool GetMouseButtonDown(int button, bool setHandled);
public static bool GetMouseButtonUp(int button, bool setHandled);
public static bool GetMouseButton(int button, bool setHandled);      // setHandled unused; returns Input.GetMouseButton
public static bool GetMouseButtonHeld(int button[, bool setHandled]); // hold-timer based (s_heldMouseButtons)
public static bool GetKeyDown(KeyCode key[, bool setHandled]);
public static bool GetKeyUp(KeyCode key[, bool setHandled]);
public static bool GetKey(KeyCode key);                              // PURE passthrough — does NOT check DisableInput
public static bool GetShiftkey(); GetControlkey(); GetAltkey(); GetCommandKey();
public static bool GetDoublePressed(KeyCode key, bool handle);
// mapped controls — resolve MappedControl → List<KeyControl> via GameState.Controls, then funnel into the KeyControl overloads:
public static bool GetControl(MappedControl control);   GetControl(MappedControl, bool ignoreHandle, bool ignoreModifiers);
public static bool GetControlDown(MappedControl control[, bool handle]);   GetControlUp(MappedControl control[, bool handle]);
public static bool GetControlDown(KeyControl control, bool handle);        GetControlUp(KeyControl control, bool handle);   // ← THE funnels (call Input.GetKeyDown/Up + modifier check)
public static bool GetControl(KeyControl control, bool ignoreHandle, bool ignoreModifiers);
public static bool GetControlDoublePressed(MappedControl control);
public static bool GetControlDownWithoutModifiers(MappedControl/KeyControl);  GetControlUpWithoutModifiers(...);
// blocking / consuming:
public static void HandleAllKeys(); HandleAllClicks(); BeginBlockAllKeys(); EndBlockAllKeys();
public static void HandleAllKeysExcept(KeyCode / KeyCode,KeyCode / MappedControl);  HandleAllClicksExcept(KeyCode / KeyCode[]);
public static bool LmbAvailable();
public static bool SelectDead;                                       // public static field
public event HandleInput OnHandleInput;                              // instance event, fired at END of Update() — post-pick hook
```
**Virtual-input injection verdict [verified]:**
- **Buttons/keys:** prefix `GetMouseButtonDown/Up/GetMouseButton(int,bool)`, `GetKeyDown/GetKeyUp(KeyCode,bool)`, `GetKey(KeyCode)`, and the **KeyControl funnels** `GetControlDown/GetControlUp(KeyControl,bool)` + `GetControl(KeyControl,bool,bool)` (single choke point for all mapped controls), plus the `NumberPressed` getter. Return injected state via `__result`, skip original.
- **Cursor position / world pick:** prefixing `MousePosition` alone is NOT sufficient — `GameInput.Update()` reads **`Input.mousePosition` directly** for the Walkable-layer raycast and the character-hover scan, then publishes results to `s_pickLocation`, `GameCursor.WorldPickPosition`, and `GameCursor.CharacterUnderCursor`. Easiest full injection: **postfix `GameInput.Update`** (private instance method — patchable) and overwrite the outcome statics — `GameCursor.WorldPickPosition { get; set; }` and `GameCursor.CharacterUnderCursor` are **publicly settable** [verified SDK/GameCursor.cs L115/L39] — plus prefix `MousePosition`/`GlobalMousePosition` getters for UI code that reads them (e.g. `UIConversationManager.HandleInput`'s `TextList.LineAt(GameInput.MousePosition)`).
- `DisableInput` gates everything except `GetKey`; keep it false while injecting, or bypass it in your prefixes.

### SDK.GameCursor [verified, firstpass/SDK/GameCursor.cs]
```csharp
public static Vector3 WorldPickPosition { get; set; }        // L115 — SETTABLE
public static GameObject CharacterUnderCursor { get; set; }  // L39 — settable
public static GameObject GenericUnderCursor;  ObjectUnderCursor;  OverrideCharacterUnderCursor;   // L59/87/17
public static Collider2D ColliderUnderCursor { get; set; }   // L103
public static Usable UnusableUnderCursor { get; set; }   public static bool BlockCursor { get; set; }   // L37/19
public static GameCursor Instance => s_instance;             // L35
```
Game layer [HERE]: `GameCursor.LockCursor { get; set; }`, `DesiredCursor/UiCursor/ActiveCursor/CursorOverride` (CursorType enum, 50+ values), `UiObjectUnderCursor` (static field).

### NGUI UICamera [HERE, Assembly-CSharp/UICamera.cs] — CONFIRMED hooks:
```csharp
public static UICamera.OnCustomInput onCustomInput;   // L106 — static delegate invoked every UICamera.Update (L660-662). Feed virtual NGUI nav here.
public static bool inputHasFocus;                     // L124 — true when an NGUI UIInput has focus (text entry active).
```
IMPORTANT: `UICamera` reads **raw `UnityEngine.Input.GetKeyDown(...)` directly** for UI navigation (arrows/submit/cancel/tab/delete — L449-923), NOT `GameInput`. So generic NGUI menu nav needs raw-Input-level injection or `onCustomInput`; the conversation option path however goes through `GameInput` (§3) and is coverable via the GameInput seam alone. Plan for BOTH seams.

---

## 10. Character creation & level-up UI — `UICharacterCreationManager.cs` [HERE] + ~55 `UICharacterCreation*` files

`public static UICharacterCreationManager Instance => s_Instance;` — non-null only while the creation screen exists → **mode detection: `UICharacterCreationManager.Instance != null`** (used exactly so in `GameState.Update()` L716). New-game flow loads scene `"LifePath"` (§11). Level-up shares `UICharacterCreation*` widgets (`UICharacterCreationController/Stage/NavControl`).
Name entry: `UICharacterCreationNameSetter.cs` [HERE] drives the name field via `base.Owner.Character.Name`, with `IsValidName(string)` validation and an `ErrorIndicator` shown when the name is empty/invalid (L120). **A valid non-empty name appears required to advance** — a headless flow must set `Character.Name` to a valid string programmatically. Creation screens are normal NGUI cursor+click (BoxColliders + UICamera → raw UnityEngine.Input, see §9). `Time.timeScale` force-managed during creation (`UICharacterCreationEnumSetter.cs:643-646`).

---

## 11. New game / main menu — `UIMainMenuManager.cs`, `UINewGameScreen.cs` [HERE]

Main menu: `UIMainMenuManager.Instance` (static), `NewGameScreen` field, `MenuActive/MenuLocked`, `static StartingGame()`; scene `"MainMenu"`. New Game button → `UIMainMenuManager.Instance.NewGameScreen.OpenScreen()` (`UIMainMenuClickHandler.cs` L148).
```csharp
public void UINewGameScreen.OpenScreen();
public void UINewGameScreen.OnAcceptClick(GameObject go);   // reads difficulty/ToI/Expert/Legacy → GameState.Mode, then StartIntro()
private void StartIntro();      // SDK.GameState.NewGame = true; GameState.Instance.PlaythroughGUID = Guid.NewGuid();  [PlaythroughGUID verified: SDK/GameState.cs L118]
                                //   UIMainMenuManager.StartingGame(); UILoadingScreen.Show(Character_Creation, → SceneManager.LoadScene("LifePath"))
```
**Programmatic new game:** drive `OpenScreen()` + `OnAcceptClick(null)`, or replicate `StartIntro` (set `SDK.GameState.NewGame = true`, `Game.GameState.Instance.NewGamePlusIteration = 0`, `PlaythroughGUID = Guid.NewGuid()`, then `SceneManager.LoadScene("LifePath")`). Set `Game.GameState.Mode` difficulty first.
**Return to main menu:** `Game.GameState.LoadMainMenu(bool fadeOut)` [HERE]; error path `ReturnToMainMenuFromError()`.

---

## 12. Debug console — `SDK.CommandLine.RunCommand` [verified, firstpass/SDK/CommandLine.cs L295-478]

```csharp
public static void RunCommand(string command);   // namespace SDK — VERIFIED (public static void)
```
Verified behavior: splits on `,` into multiple commands; each split on spaces (arg0 = method name, case-insensitive). Reflects over **`Game.CommandLine` public statics always**; additionally over **`Game.Scripts` public statics ONLY when `SDK.GameState.CheatsEnabled`**. Methods carrying `[Cheat]` also require CheatsEnabled. Matches on name + exact param count; coerces params (enums via `Enum.Parse`, `Guid` with GameObject-name fallback, quest/conversation browser lookups, `Convert.ChangeType` for value types). Errors → `Console.AddMessage(..., Color.yellow)`.
⇒ **`reputationaddpoints` lives in `Game.Scripts` (Assembly-CSharp/Scripts.cs — verified sole match) ⇒ requires `SDK.GameState.CheatsEnabled = true`** (set the property directly, or call `Game.CommandLine.IRoll20s()` which also disables achievements).

Directly-callable `Game.CommandLine` statics [HERE], many `[Cheat]`-tagged: `ResetParty()`, `Damage(string)`, `Difficulty(string)`, `AddItem(string,string)`, `AttributeScore/Skill(name,which,val)`, `AddAbility/RemoveAbility`, `SetTime(string)`, `AdvanceDay()`, `Edict(tag)/RemoveEdict()/LearnEdictPackage(tag)`, `AddBelief/SpendBelief(string)`, `AddCompanion(name)/AddAllCompanions()`, `SpawnPrefabAtMouse/AtPoint(...)`, `UnlockAllMaps()`, `SetMaxFPS(int)`, `Flash(float)`.

**Console output [verified, firstpass/Console.cs]:**
```csharp
public static Console Instance { get; private set; }                          // L187
public static void AddMessage(string msg);                                    // L298
public static void AddMessage(string msg, ConsoleState mode);                 // L288
public static void AddMessage(string msg, Color color);                       // L308
public static void AddMessage(string msg, Color color, ConsoleState mode);    // L293
public static void AddMessage(string msg, string verbose);                    // L303
public static void AddMessage(string msg, string verbose, Color color);       // L313
public static string Format(string fstring, params object[] parameters);      // L331
public enum ConsoleState { ... }   // L10 (DIALOG_BIG, DEBUG, ... per usage)
```
UI console box: `UICommandLine.cs` [HERE] → `CommandLine.RunCommand(text)` on submit; toggled by `MappedControl.TOGGLE_CONSOLE`.

---

## Extras

### Edict / timer mechanics [HERE — `Game/EdictManager.cs`, `Game/Edict.cs`]
`EdictManager.Instance` (public static field), `GetActiveEdict([Region])`, `GetEdictPackageByTag/GetEdictByTag(string)`, `ActivateEdictPackage(Region|string, EdictPackage|string)`, `DeactivateEdict(Region|string)`, `LearnEdictPackage(string|EdictPackage)`, `IsEdictPackageActive(string)`; static events `EdictPreActivated/EdictPostActivated/EdictPreDeactivated/EdictPostDeactivated` (EventHandler). `Edict`: `.Tag`, `.EdictNameText/Description/BreakText`, `Activate()/Deactivate()`, `getBreakVar()` (reads GlobalVariables). Countdown = WorldTime date math + globals (§7).

### Area transition events [verified]
`SDK.GameState.LevelUnload/LevelLoadedEarly/LevelLoaded/LevelLoadedLate/Resting` static events (SDK/GameState.cs L166-174). `ScriptEvent.BroadcastEvent(ScriptEvent.ScriptEvents.OnSceneExited/OnLevelLoaded)`. `Game.GameState.ChangeLevel(...)` initiates transitions.

### Party enumeration — `SDK.PartyMemberAI` [verified, firstpass/SDK/PartyMemberAI.cs]
```csharp
public static PartyMemberAI[] PartyMembers;                    // L33 — public static field (null slots = empty)
public static List<PartyMemberAI> OnlyPrimaryPartyMembers { get; }   // L154
public static GameObject[] SelectedPartyMembers { get; }       // L383 — static property
public static int NumPrimaryPartyMembers { get; }  NextAvailablePrimarySlot { get; }  // L174/395
public static int MAX_PARTY_MEMBERS => (MAX_SECONDARY_SLOTS + 1) * MAX_PRIMARY_PARTY_MEMBERS;   // L104 (Game sets 4+4 → 20 slots incl. summons)
public static event EventHandler PartyMembersChanged;          // L426
public static event EventHandler OnAnySelectionChanged;        // L428  <-- selection-change event
public static event Action OnPartyOrderChanged;                // L432
public virtual bool Selected { get; set; }                     // L260 — per-member selection (writes its SelectedPartyMembers slot)
public bool DragSelected { get; set; }                         // L297
public static int GetSelectedLeaderSlot();  public static int NumSelectedMembers();   // L827/839
public static void EnsurePartyMemberSelected();                // L639
// Game layer [HERE]: static AddToActiveParty(GameObject, bool fromScript); RemoveFromActiveParty(PartyMemberAI); PopAllStates(); Reset();
//                    instance: Slot, AssignedSlot, IsActiveInParty, IsAdventurer, ReputationFaction (FactionName)
```

### Per-character health [verified]
```csharp
// SDK.Health (firstpass/SDK/Health.cs):
public virtual float CurrentHealth { get; set; }               // L57
public abstract bool Dead { get; set; }                        // L81
public abstract bool ShowDead { get; }                         // L85
public abstract void ApplyHealthChangeDirectly(float amount, bool applyIfDead);   // L235 (+3 overloads: healer GameObject, StatusEffect, bool showInConsole)
// MaxHealth is on Game.Health (Assembly-CSharp/Game/Health.cs L380): public float MaxHealth { get; }
//   plus PreWoundsMaxHealth (L364). SDK.CharacterStats: public float BaseMaxHealth = 100f (field, L67); Game.CharacterStats: DerivedMaxHealth.
// Game.Health extras [HERE]: static ResetCharacter(GameObject); static bool BloodyMess; DeathStatusType { INVALID=-1, KO, Death };
//   OnyxEvent OnWouldHaveKilled / OnPartyWouldHaveKilled.
```
Get HP: `go.GetComponent<Game.Health>().CurrentHealth / .MaxHealth`. Position = `component.transform.position`. Player stats: `GameState.s_playerCharacter.Character` (Game.CharacterStats: `Level`, `ActiveAbilities`, `Name()`, static `NameColored(GameObject)`, skill props, `AttributeScoreType`/`SkillType` enums, `SetBaseAttributeScore`).

### Networking check (TcpListener long-shot) — RESOLVED: nothing unusual in game code
Searched both assemblies for `TcpListener` / `System.Net.Sockets` / raw `Socket` usage: **zero hits** in game code. The only network-adjacent code is Steamworks (`firstpass/Steamworks/SteamNetworking.cs`, `SteamGameServerNetworking.cs` — Steam P2P API over the Steam client, not OS sockets) and one `using System.Net` in `Game/FeedProvider_Paradox.cs` (HTTP news feed). No socket hooking, no interception, nothing that would make `TcpListener.Start()` succeed without a real bind. If a plugin's listener port is invisible in netstat, suspect the **runtime/environment, not the game**: Unity 5.4 ships an ancient Mono 2.x-era class library whose `TcpListener` can end up bound IPv6-only (check `netstat -ano` for `[::]:port`, not just `0.0.0.0:port`), or the listener was GC'd/closed. Verify from inside the process with `IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners()`, construct with explicit `new TcpListener(IPAddress.Any /* or Loopback */, port)`, and hold a strong reference.

---

## Harmony targeting cheat-sheet (all targets verified unless noted)
| Need | Target | Kind |
|---|---|---|
| Combat on/off events | `SDK.GameState.CombatStart` / `CombatEnd` (static events) | subscribe |
| Read combat/loading/gameover/paused | `SDK.GameState.InCombat/IsLoading/GameOver/Paused` | read static |
| Area-load finished | `Game.GameState.FinalizeLevelLoad` postfix, or `SDK.GameState.LevelLoaded` event, or `SDK.GameResources.EventLoadedSave` | postfix / subscribe |
| Intercept option text | `Conversation.GetNodeText(FlowChartPlayer, FlowChartNode, bool, NodeTextRequestType)` | postfix (swap `__result`) |
| Shuffle option order | `Conversation.GetResponseNodes(FlowChartPlayer)` + 2-arg overload | postfix (reorder list) |
| Which option chosen / inject choice | `UIConversationManager.PlayerInput(int)` (private) | postfix / invoke |
| Start a conversation | `ConversationManager.Instance.StartConversation(file, owner, DisplayMode[, disableVo])` | call |
| Favor/wrath stream | `Game.ReputationManager.AddReputation/RemoveReputation` (5-arg overloads) | postfix |
| Read favor/wrath | `GetReputation((int)FactionName.X)` → `.PositiveAxisValue/.NegativeAxisValue/.GoodRank/.BadRank` | read |
| Quest milestones | `QuestManager.OnQuestAdvanced/OnQuestCompleted/OnQuestFailed/OnQuestStarted` (delegate FIELDS — Delegate.Combine) or postfix `TriggerQuestEndState` | combine / postfix |
| Global-var mutations | `GlobalVariables.SetVariable(string,int)` postfix, or postfix `QuestManager.TriggerGlobalVariableEvent(string,int)` | postfix |
| Inject buttons/keys | `GameInput.GetMouseButtonDown/Up/GetMouseButton(int,bool)`, `GetKeyDown/Up(KeyCode,bool)`, `GetKey(KeyCode)`, `GetControlDown/Up(KeyControl,bool)`, `GetControl(KeyControl,bool,bool)`, `NumberPressed` getter | prefix (skip, set `__result`) |
| Inject cursor/world-pick | postfix `GameInput.Update` then set `GameCursor.WorldPickPosition` / `GameCursor.CharacterUnderCursor` (both settable); prefix `GameInput.MousePosition`/`GlobalMousePosition` getters | postfix + prefix |
| NGUI menu input | `UICamera.onCustomInput` static delegate; raw `UnityEngine.Input` (UICamera bypasses GameInput) | assign / low-level |
| Game speed (arbitrary) | `TimeController.Instance.Flash(float)` (public), or set `NormalTime` field / private `m_TimeScale`; final authority = postfix private `TimeController.UpdateTimeScale()` | call / reflection / postfix |
| Pause | `TimeController.Instance.Paused` / `SafePaused` setters; `PauseChanged` event | set / subscribe |
| Save / load | `Game.GameResources.SaveGame(string[,string,bool])` / `LoadGame(string)` (static) | call |
| Redirect save dir | prefix `SDK.GameResources.SaveGamePath` getter **+ rewrite `PersistenceManager.s_tempSavePath/s_mobileObjPath/s_oldTempSavePath` public static fields + patch `GlobalVariables.Write/ReadGlobalsToSaveGame`** (hardcoded persistentDataPath/CurrentGame) | prefix + field writes |
| Run console command | `SDK.CommandLine.RunCommand(string)` — set `SDK.GameState.CheatsEnabled = true` first for `[Cheat]`/`Game.Scripts` commands (incl. `reputationaddpoints`) | call |
| New game | `UINewGameScreen.OpenScreen`/`OnAcceptClick`, or replicate `StartIntro` + `LoadScene("LifePath")` | call |
| To main menu | `Game.GameState.LoadMainMenu(bool)` | call |
| In char-creation? | `UICharacterCreationManager.Instance != null` | read |
| Party / selection | `SDK.PartyMemberAI.PartyMembers` (field), `SelectedPartyMembers`, `OnAnySelectionChanged` event, `Selected` prop | read / subscribe |
| HP | `go.GetComponent<Game.Health>().CurrentHealth` (SDK virtual) / `.MaxHealth` (Game layer) | read |

## Remaining unverified (OEIFormats.dll only)
`FlowChartNode` / `PlayerResponseNode` / `DialogueNode` / `ScriptNode` member details (`NodeID`, `NodeType`, `Links`, `Persistence`, `Conditionals`, `HideSpeaker`, `ClassExtender`) are usage-derived from verified call-sites — decompile `OEIFormats.dll` only if a patch must target them directly (none of the planned hooks do; all planned hooks target Conversation/ConversationManager/UIConversationManager/GameInput, which are fully verified).
