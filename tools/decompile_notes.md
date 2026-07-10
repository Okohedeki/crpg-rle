# Tyranny Decompile Notes — Harmony Hook Reference

Source: ILSpy decompile of `Assembly-CSharp.dll` at `H:\RL\tools\extracted\assembly_csharp\` (1147 .cs).
Game: Tyranny (Obsidian 2016), Unity 5.4 Mono, OEI/PoE1 shared engine. NGUI UI.

## CRITICAL ARCHITECTURE NOTE — read first

The decompiled assembly contains only two layers:
- **`Game.*` namespace** (files in `Game/` subdir): the game-specific subclasses, e.g. `Game.GameState : SDK.GameState`, `Game.Reputation : SDK.Reputation`, `Game.WorldTime : SDK.WorldTime`, `Game.GameResources : SDK.GameResources`, `Game.CommandLine : SDK.CommandLine`, etc.
- **Global-namespace UI classes** (files in root): `UIConversationManager`, `UIMainMenuManager`, `UICommandLine`, `UICharacterCreationManager`, etc.

**The entire `SDK.*` base layer is in a SEPARATE assembly that was NOT decompiled here** (likely `Assembly-CSharp-firstpass.dll` / an OEI SDK dll). `grep "namespace SDK"` returns 0 hits. This means:
- Many core engine types have **no source here at all**: `SDK.GameInput`, `SDK.Console`, `SDK.GlobalVariables`, `SDK.TimeController`, `SDK.PersistenceManager`, `SDK.SaveGameInfo`, `OEIFormats.FlowCharts.Conversations.Conversation`, `ConversationManager`, `FlowChartPlayer`, `PlayerResponseNode`, `SDK.CharacterStats`, `SDK.Health`, `SDK.PartyMemberAI`, `SDK.Faction`, `SDK.QuestManager` base.
- All signatures below marked **[SDK, inferred]** were reconstructed from *usage* in the decompiled Game-layer code. Member names/params are reliable (they compile against the real DLL), but you should confirm exact overload/visibility against the shipped `Assembly-CSharp-firstpass.dll` with dnSpy/ILSpy before finalizing a patch. Types marked **[HERE]** are fully decompiled in this assembly.
- For Harmony: you can `AccessTools.TypeByName("SDK.GameState")` etc. at runtime regardless of which DLL — the CLR resolves across assemblies. Patch targets in the SDK layer are fully reachable; you just can't read their bodies here.

Namespaces are file-scoped (`namespace Game;`). `using SDK;` means unqualified `GameInput`, `Console`, `GlobalVariables`, `TimeController` in Game-layer code all resolve to `SDK.*`.

---

## 1. GameState  — `Game/GameState.cs` [HERE], base `SDK.GameState` [SDK]

`public class Game.GameState : SDK.GameState` (a MonoBehaviour singleton).

**Singleton / player access:**
```csharp
public new static GameState Instance => SDK.GameState.s_instance as GameState;   // [HERE]
public new static Player s_playerCharacter { get; set; }   // [HERE] override wrapper; base SDK field SDK.GameState.s_playerCharacter (a CharacterStats-ish); here returns Game.Player
protected static SDK.GameState.s_instance                  // [SDK] backing field, MonoBehaviour
public static event EventHandler PlayerCharacterChanged;    // [HERE]
```
`GameState.Instance` is the go-to accessor. `GameState.s_playerCharacter` is `Game.Player` (has `.gameObject`, `.Character` (CharacterStats), `.GetComponent<...>()`).

**Combat flag** (all [SDK] statics, set inside `Game.GameState.UpdateIsInCombatAndGameOver()` [HERE]):
```csharp
SDK.GameState.InCombat        // static bool property (public getter)  -> READ combat state
SDK.GameState.s_isInCombat    // static bool backing field
public static bool CannotSaveBecauseInCombat => SDK.GameState.s_isInCombat || s_noSaveInCombatCountdown > 0;  // [HERE]
public static bool IsInTrapTriggeredCombat { get; }  // [HERE]
public static float InCombatDuration => s_inCombatTimer;  // [HERE]
public static bool ForceCombatMode { get; set; }  // [HERE] force combat on
```
Combat start/end raise `SDK.GameState.OnCombatStart` / `OnCombatEnd` (EventHandler events) — good postfix/subscribe points. `UpdateIsInCombatAndGameOver()` runs every `Update()`.

**Paused state:** owned by `TimeController` (see §7), NOT GameState. `SDK.GameState.Paused` [SDK] static bool exists (used in `UpdateIsInCombatAndGameOver`: `if (SDK.GameState.Paused ...) return;`) and mirrors TimeController pause.

**Current map / area:**
```csharp
public MapData GetCurrentMap();  public void SetCurrentMap(MapData);   // [HERE] instance
public MapData GetLastMap();  public MapData GetCurrentNextMap();
public Region CurrentRegion { get; }                 // [HERE] current world Region
public override string GetCurrentMapName();          // [HERE] returns MapData.GetDisplayNameText()
public bool CurrentMapIsStronghold { get; }
SDK.GameState.LoadedLevelName   // [SDK] static string — the scene name currently loaded
SDK.GameState.ApplicationLoadedLevelName  // [SDK] static string
```

**Game-over / death:**
```csharp
SDK.GameState.GameOver / SDK.GameState.s_gameOver   // [SDK] static bool (s_gameOver set true when PartyDead)
SDK.GameState.PartyDead                              // [SDK] static bool
public static bool CutsceneAllowed => !SDK.GameState.PartyDead && !SDK.GameState.GameOver;  // [HERE]
```
On game over, `UIDeathManager.Instance.ShowWindow()` is called ~2s after PartyDead.

**Loading state:**
```csharp
SDK.GameState.IsLoading         // [SDK] static bool — true during level transition, set false in FinalizeLevelLoad()
SDK.GameState.IsTransitionInProgress  // [SDK] static bool
SDK.GameState.IsRestoredLevel   // [SDK] static bool
SDK.GameState.LoadedGame / NewGame / FirstPlaythrough  // [SDK] static bool flags
SDK.GameState.NumSceneLoads     // [SDK] static int
public void FinalizeLevelLoad();  // [HERE] fires OnLevelLoaded* events, sets IsLoading=false — HOOK for "load complete"
```

**Scene transition helpers [HERE, static]:** `LoadMainMenu(bool fadeOut)`, `ChangeLevel(MapData/MapType/string)`, `LoadLevel(MapData/string)`, `BeginLevelUnload(string)`, `Autosave()`, `EndGameAndLoadCredits()`, `ReturnToMainMenuFromError()`.

**Difficulty / mode:** `public static GameMode Mode;` and `public static GameMode Option => Mode;` [HERE]. `Difficulty` (GameDifficulty), `TrialOfIron`, `ExpertMode` persistent props.

**Verdict:** Read combat/loading/gameover via `SDK.GameState` static props (`InCombat`, `IsLoading`, `GameOver`, `Paused`). Subscribe to `OnCombatStart/OnCombatEnd` events. `GameState.Instance` for map/region. Postfix `FinalizeLevelLoad` = "area load finished" event. All read-via-static-singleton; no virtual override needed.

---

## 2. Conversation system  [SDK / OEIFormats, inferred] + `UIConversationManager` [HERE]

Core flow classes live in `OEIFormats.FlowCharts` / `OEIFormats.FlowCharts.Conversations` / `SDK` (NOT decompiled here). All signatures below reconstructed from `UIConversationManager.cs` and `GameState.cs`/`GameResources.cs` usage.

**Access to active conversation:**
```csharp
ConversationManager.Instance                                   // static singleton [SDK]
ConversationManager.Instance.GetActiveConversationForHUD()     // -> FlowChartPlayer (null if none)
ConversationManager.IsWMEConversation(FlowChartPlayer)         // static bool (world-map-event convo)
ConversationManager.Instance.EndConversation(FlowChartPlayer)
ConversationManager.Instance.SetNodeCompleted(Conversation, int nodeId, bool complete)
ConversationManager.Instance.GetNodeCompleted(Conversation, int nodeId)  // -> bool
ConversationManager.Instance.GetMarkedAsRead(Conversation, int nodeId)   // -> bool
ConversationManager.Instance.ReactivityPanelFadeTime           // float
// delegate + event:
ConversationManager.FlowChartPlayerDelegate  (void (FlowChartPlayer))
ConversationManager.Instance.FlowChartPlayerAdded  // event of above delegate
public static bool UIConversationManager.IsInConversation()    // [HERE] convenience
```

**FlowChartPlayer** (the runtime cursor over a flowchart) [SDK]:
```csharp
.CurrentFlowChart      // FlowChart  (cast `as Conversation`)
.CurrentNodeID         // int   <-- current node id
.FlowChartDisplayMode  // FlowChartPlayer.DisplayMode enum { Standard, ... }
.FadeFromBlackOnExit   // bool
.Filename              // string (dialogue asset name)
```

**Conversation** (`OEIFormats.FlowCharts.Conversations.Conversation`) [SDK] — key methods used by UI:
```csharp
List<PlayerResponseNode> GetResponseNodes(FlowChartPlayer player);                 // ALL response links from current question node
List<PlayerResponseNode> GetResponseNodes(FlowChartPlayer player, bool qualifiedOnly);
FlowChartNode GetNextNode(FlowChartPlayer player);
FlowChartNode GetNode(int nodeId);
string GetActiveNodeText(FlowChartPlayer player);                                  // speaker/current node text
string GetNodeText(FlowChartPlayer player, FlowChartNode node, bool forPlayerInput);
string GetNodeText(FlowChartPlayer player, FlowChartNode node, bool forPlayerInput, Conversation.NodeTextRequestType);  // NodeTextRequestType { PassingOnly, ... }
string GetNodeQualifier(FlowChartNode node, FlowChartPlayer player);
List<NodeQualifierBase> GetNodeQualifiersHelper(PlayerResponseNode, FlowChartPlayer, bool checkpassing, bool passing, bool firstonly, bool forDisplayPurposes);
bool PassesConditionalsEx(PlayerResponseNode response, FlowChartPlayer player);    // is option selectable
void MoveToNode(int nodeId, FlowChartPlayer player);                               // ADVANCE conversation
void MoveToPreviousNode(FlowChartPlayer player);
List<FlowChartNode> GetAllNodesFromActiveNode(FlowChartPlayer player);             // debug mode enumeration
static GameObject GetSpeaker(FlowChartPlayer player);
static bool LocalizationDebuggingEnabled;   // static field
static void ClearSpeakerGUIDCache();
enum NodeTextRequestType { PassingOnly, ... }
```
**PlayerResponseNode / FlowChartNode** [SDK]:
```csharp
FlowChartNode.NodeID          // int
FlowChartNode.NodeType        // FlowChartNodeType enum { PlayerResponse, ... }
FlowChartNode.Links           // list of links
FlowChartNode.ClassExtender.GetExtendedPropertyValue(string)  // e.g. "MaintainsStealth"
PlayerResponseNode.Conditionals.Components   // list; Count>0 => stat-check option
PlayerResponseNode.Persistence               // PersistenceType (MarkAsRead, ...)
DialogueNode.HideSpeaker (bool), .DefaultMood; ScriptNode : FlowChartNode
```
Display text is resolved through the flowchart's own StringTable (via `GetNodeText`/`GetActiveNodeText`); the returned string is already localized. The `int nodeID` maps to VO via `GameResources.GetVOAssetForConversation(dialogueName, nodeID, useFemale)`.

**Pick a response programmatically:** call `conversation.MoveToNode(responseNodes[i].NodeID, player)` then advance (see `UIConversationManager.PlayerInput`). Or drive the UI method directly (§3).

**Verdict:** Active convo read via `ConversationManager.Instance.GetActiveConversationForHUD()`. To intercept option text before render → postfix `Conversation.GetNodeText` (swap string) and/or `Conversation.GetResponseNodes` (reorder the returned List = shuffle). To know which option was chosen → patch `UIConversationManager.PlayerInput(int)` (§3). All SDK-side but Harmony-reachable.

---

## 3. Dialogue UI  — `UIConversationManager.cs` [HERE]  (`: UIHudWindow`, global namespace)

Singleton: `public static UIConversationManager Instance => s_Instance;` (`private static UIConversationManager s_Instance`).
Active flowchart cached in fields: `private FlowChartPlayer m_ActiveFlowChart;  private int m_CurrentNodeId;`
`private Conversation conversation => m_ActiveFlowChart?.CurrentFlowChart as Conversation;` (private prop).
Text is drawn into `UIConsoleText ConversationTextList` (public field, alias `TextList`) — an NGUI `UILabel`-backed list. `ContinueButton` (UIMultiSpriteImageButton), `ContinueButtonLabel` (UILabel).

**THE patch point for building the on-screen response list:**
```csharp
private int DrawResponses();        // [HERE] normal mode — iterates conversation.GetResponseNodes(m_ActiveFlowChart),
                                    //   formats "<n>. <text>" via conversation.GetNodeText(...), calls TextList.Add(text). Returns line count.
private int DrawResponsesDebug();   // [HERE] localization-debug mode
```
`DrawResponses` reads `GetResponseNodes` order and numbers options 1..N. To **shuffle order** postfix/prefix `Conversation.GetResponseNodes` to reorder the list (cleaner than transpiling DrawResponses). To **swap text** postfix `Conversation.GetNodeText`. `DrawResponses` is called from `CheckRecreateContent()` [HERE] which is the per-frame rebuild driver (called from `Update()` when node changes or `ForceRefresh`).

**Click / number-key → response index:**
```csharp
public override void HandleInput();   // [HERE] the input router. Uses:
  int num  = TextList.LineAt(GameInput.MousePosition);   // screen line under cursor
  int idx  = LineToResponse(num);                        // private int LineToResponse(int line) => m_OutstandingResponses - TextList.ParagraphCount + line
  if (GameInput.NumberPressed > 0) PlayerKeyInput(GameInput.NumberPressed - 1);      // number keys 1-9
  GameInput.GetMouseButtonDown(0, true) / GetMouseButtonUp(0, true)  -> PlayerKeyInput(idx)
  GameInput.GetControlDown(MappedControl.CONV_CONTINUE) -> continue button
private void PlayerKeyInput(int number);   // [HERE] dispatches to PlayerInput/PlayerInputDebug
private void PlayerInput(int number);      // [HERE] <-- THE method invoked when player picks response index `number` (0-based).
                                           //   validates via PassesConditionalsEx, calls MoveToNode(responseNodes[number].NodeID,...)
```
**Verdict:** Postfix `UIConversationManager.PlayerInput(int)` to observe/redirect the chosen index (0-based, indexes into `conversation.GetResponseNodes(m_ActiveFlowChart)`). To inject a choice, call `PlayerInput(i)` directly (public reflection) or feed virtual input so `HandleInput` picks it up. For text-swap + shuffle, hook the SDK `Conversation` methods above. `IsInConversation()` (static, [HERE]) is the gate.

---

## 4. Reputation / factions

### FactionName enum — `FactionName.cs` [HERE]  (global namespace, int-backed)
`None=0, ScarletChorus=1, Disfavored=2, Comp_Beastman=3 ... SK_Tunon=24, SK_GravenAshe=25, SK_VoicesSoldak=26, SK_BledenMark=27, Art_* ..., Player=64, ...` (117 values). These ints ARE the reputation/faction ids used everywhere (`(int)FactionName.SK_GravenAshe` == reputation id).

### Reputation — `Game/Reputation.cs` [HERE] : `SDK.Reputation`
```csharp
public FactionName FactionID;                    // this rep's faction
public ReputationType Type;                       // enum { Faction, Companion, Artifact, Archon, Count }
enum ChangeStrength { None, VeryMinor, Minor, Average, Major, VeryMajor }  // (SDK.Reputation.ChangeStrength)
enum Axis { Positive, Negative }                  // (SDK.Reputation.Axis) — Positive=Favor, Negative=Wrath
```
**Read current favor/wrath** (base `SDK.Reputation` props, used throughout [SDK, inferred]):
```csharp
int  base.PositiveAxisValue  { get; set; }   // raw Favor points
int  base.NegativeAxisValue  { get; set; }   // raw Wrath points
int  base.GoodRank { get; }                  // Favor rank (0..MaxRank)
int  base.BadRank  { get; }                  // Wrath rank
int  GetRank(out RankType rankType);         // RankType { Good, Bad, Mixed }
float GetReputationPct(Axis axis);
int  GetScaleForAxis(Axis axis);
static int SDK.Reputation.MaxRank;           // static (==5 effectively)
DatabaseString Name; Name.GetText();  Description;
```
Game-layer helpers [HERE]: `IsFriendly()`, `IsHostile()`, `GetMaxRank(Axis)`, `int RecordCount`, `List<ChangeEvent> GetChangeEventsForAxis(Axis)`, `ForceHostile(int reason)`, `SetAxisRank(Axis, int rank, int reason)`, `AppendTooltipRankInfo(StringBuilder)`.
`Reputation.ChangeEvent` [HERE] nested: `{ ChangeEventType m_type; Axis m_axis; ChangeStrength m_strength; int m_reasonIndex; string ReasonText; }`.

### ReputationManager — `Game/ReputationManager.cs` [HERE] : `SDK.ReputationManager`
```csharp
public new static ReputationManager Instance => SDK.ReputationManager.s_instance as ReputationManager;  // singleton
public Reputation[] Factions;                        // all reputations
public List<FactionName> Alliance;                   // [Persistent]
public event Action<Reputation> OnReputationNewAbilityChanged;
```
**Read a faction's rep:** `SDK.Reputation GetReputation(int id, bool suppressWarnings=false)` [HERE override] — pass `(int)FactionName.X`. Cast result to `Game.Reputation`.
**MUTATORS = favor/wrath event stream (postfix these) [HERE]:**
```csharp
public bool AddReputation(SDK.Reputation rep, Axis axis, ChangeStrength strength);                                  // override
public bool AddReputation(SDK.Reputation rep, Axis axis, ChangeStrength strength, int reasonIndex, bool ignoreLinkedReputations=false);   // <-- canonical add
public bool AddReputation(int factionId, Axis axis, ChangeStrength strength, int reasonIndex, bool ignoreLinkedReputations=false);
public bool RemoveReputation(... same overloads ...);
public string GetFactionName(FactionName id);
public FactionName[] GetKnownFactionsOfType(Reputation.ReputationType, bool excludeNoLinks, bool excludeNoAbilities);
```
Note: adds are suppressed mid-conversation-node if the node was already completed (guards double-award). Belief is granted when `strength >= BeliefRepThreshold`.

### Faction — `Game/Faction.cs` [HERE] : `SDK.Faction` — this is the TEAM/hostility component (per-GameObject), distinct from Reputation. `SDK.Faction.ActiveFactionComponents` (static list, used in combat check), `faction.IsHostile(otherFaction)`, `CurrentTeam`/`CurrentTeamInstance`. `PartyMemberAI.ReputationFaction` (FactionName) links a companion to its Reputation.

**Verdict:** Read favor/wrath via `ReputationManager.Instance.GetReputation((int)FactionName.X)` then `.PositiveAxisValue`/`.NegativeAxisValue`/`.GoodRank`/`.BadRank`. Postfix `ReputationManager.AddReputation`/`RemoveReputation` (the `(rep, axis, strength, reasonIndex, ignoreLinked)` overload) for a favor-event stream. Console cheat `reputationaddpoints` (SDK.CommandLine) ultimately calls these.

---

## 5. Quests  — `Game/QuestManager.cs` [HERE] : `SDK.QuestManager`
```csharp
public new static QuestManager Instance => SDK.QuestManager.s_instance as QuestManager;   // singleton
public event SDK.QuestManager.QuestDelegate OnQuestAdvanced;   // [SDK] delegate: void QuestDelegate(Quest quest)  <-- MILESTONE EVENT STREAM
```
Quest objects: `OEIFormats.FlowCharts.Quests.Quest` [SDK]. `quest.Filename` (string id). `ObjectiveNode` [SDK].
**Advance / end-state methods (postfix = milestones):**
```csharp
protected override void CompleteQuestObjective(Quest quest, ObjectiveNode objective);   // [HERE override]
protected override void CompleteQuest(Quest quest);                                     // [HERE override]
public void CompleteAndRemoveQuest(string questName);  public void CompleteAndRemoveQuest(Quest);   // [HERE]
// inherited [SDK]:
void TriggerQuestEndState(Quest quest, int endStateIndex, bool failed);
static string SDK.QuestManager.FormatQuestName(string);
Dictionary<string,Quest> LoadedQuests;   // base.LoadedQuests keyed by Filename
base.QuestTrackers[quest.Filename].QuestLevel;   // quest tracker data
```
**Verdict:** Subscribe to `QuestManager.Instance.OnQuestAdvanced` (simplest milestone stream) OR postfix `CompleteQuest`/`CompleteQuestObjective`/`TriggerQuestEndState`. Quest ids = `quest.Filename`. Also see `TriggerQuestObjective.cs`, `UIJournalQuestObjective.cs`, `UIQuestNotifications` (`.PushQuest`).

---

## 6. Global variables  — `SDK.GlobalVariables` [SDK, inferred]  (unqualified `GlobalVariables` in Game code)
Not decompiled here; reconstructed from ~30 call sites (GameState, Edict, Conditionals, etc.):
```csharp
GlobalVariables.Instance                              // singleton (MonoBehaviour; `(bool)GlobalVariables.Instance` guards)
int  GlobalVariables.Instance.GetVariable(string name);          // returns int (game vars are ints; bool as 0/1)
void GlobalVariables.Instance.SetVariable(string name, int value);   // <-- setter; postfix = global-var change stream
static void GlobalVariables.WriteGlobalsToSaveGame();  // called in GameResources.SaveGame
static void GlobalVariables.ReadGlobalsFromSaveGame(); // called in GameResources.LoadGame
// also indexing helpers seen: GlobalVariables.Length / .Count (static-ish, on the collection)
```
Example keys seen: `"_g_Difficulty"`, `"Act1_Gameover"`, `"tel_first_playthrough"`, edict break vars (`Edict.HowToBreakEdictVar.Name`).
`GlobalVariableString` [HERE-ish] wraps a var name (`.Name`). `GlobalVariableConditional.cs`, `ConditionalizedGlobalSetting.cs` are [HERE].
**Verdict:** Read via `GlobalVariables.Instance.GetVariable("key")`. Postfix `SDK.GlobalVariables.SetVariable(string,int)` for a full mutation event stream (this is how nearly all story state flips). Confirm the exact method sig against the SDK dll (only `GetVariable`/`SetVariable` name+shape are certain here).

---

## 7. Time  — `Game/WorldTime.cs` [HERE] : `SDK.WorldTime`  +  `SDK.TimeController` [SDK]

### WorldTime (in-game calendar / Edict countdown source) [HERE]
```csharp
public new static WorldTime Instance => SDK.WorldTime.s_instance as WorldTime;
base.CurrentTime : OEIDateTime   // { int Year, Month, Day, Hour, Minute, Second; long TotalSeconds; AddSeconds/AddHours/AddYears; GetTime(); GetDate(); }
base.AdventureStart : OEIDateTime;
int TotalSecondsToday { get; }   int SecondsPerDay/Hour/Day/Year;  int HoursPerDay=24; DaysPerMonth=26; MonthsPerYear=14;
float DayNightTime { get; }      bool IsCurrentlyDaytime()/IsCurrentlyNighttime();
public void AdvanceTimeBySeconds(int);  AdvanceTimeBySeconds(int,bool isTravel,bool isResting);
public void AdvanceTimeByHours(int, bool isResting);  AdvanceTimeToHour(int);
public event WorldTimeEventHandler OnTimeJump;   // WorldTimeEventHandler(int gameSeconds, bool isMapTravel, bool isResting)  [HERE, WorldTimeEventHandler.cs]
```
The Edict/"Day of Swords" countdown is driven off `WorldTime.Instance.CurrentTime` vs target dates (see `UIWorldTimeHUDDisplay.cs`, `WorldTimeEventHandler.cs`, `AchievementTracker.HasDayOfSwordsArrive...`). No single "DayOfSwords" counter class; it's date comparisons + `GlobalVariables`.

### TimeController (pause + game speed) — `SDK.TimeController` [SDK, inferred from ~40 sites]
```csharp
TimeController.Instance                       // singleton
bool  Paused        { get; set; }             // hard pause (writes Time.timeScale internally)
bool  SafePaused    { get; set; }             // safe/auto pause (used by AutoPause, focus loss)
bool  PlayerPaused  { get; }                  // player-initiated pause
bool  Slow          { get; set; }   void ToggleSlow();   bool Fast { get; set; }   // speed tiers
bool  ProhibitPause { get; set; }             // main menu sets true
bool  UiPaused      { get; }                  // window-manager pause
bool  CanPause      { get; }
event ... PauseChanged;                       // subscribe for pause state changes (ShowOnPause.cs)
void  Flash(float speed);   static float FlashSpeed;   // flash/fast-forward
void  AddPausedSource(...); bool IsAudioSourcePaused(...);
static float TimeController.sUnscaledDelta;    // unscaled dt for UI
```
**`Time.timeScale` is written by TimeController (SDK) at runtime.** Direct `Time.timeScale = x` writes in THIS assembly are only menu/creation/credits ([UIMainMenuManager](tools/extracted/assembly_csharp/UIMainMenuManager.cs) L207/237/452 set `=1f`; `GameUtilities.cs:2465` sets `=0f`; `UICharacterCreationEnumSetter.cs:643-646`).
**Verdict — game speed control:** prefer `TimeController.Instance` (`.Slow`, `.Fast`, `.Paused`, `.SafePaused`). For arbitrary multiplier not exposed by tiers, set `UnityEngine.Time.timeScale` directly but note TimeController may overwrite it each frame — you may need to prefix-patch the TimeController setter or the property that computes timeScale. `WorldTime.Instance` for the calendar; postfix `WorldTime.AdvanceTimeBySeconds` or subscribe `OnTimeJump` for time-advance events.

---

## 8. Save / load  — `Game/GameResources.cs` [HERE] : `SDK.GameResources`  +  `SDK.SaveGameInfo` / `SDK.PersistenceManager` [SDK]

**Programmatic save [HERE, static]:**
```csharp
public static bool SaveGame(string filename);
public static bool SaveGame(string filename, string userString, bool ShouldCloudSync=false);
   // returns false if InCombat or IsTransitionInProgress; calls TakeScreenShot, FogOfWar.Save,
   // GlobalVariables.WriteGlobalsToSaveGame, SDK.GameResources.BuildSaveFile, sets SDK.GameState.LoadedFileName.
public static void Autosave();  // in GameState.cs — GameResources.SaveGame(UISaveLoadManager.GetAutosaveFileName(...))
```
**Programmatic load [HERE, static]:**
```csharp
public static bool LoadGame(string filename);         // full load: unpacks zip, LoadLevel, ReadGlobalsFromSaveGame
public static void LoadLastGame(bool fadeOut);        // loads most-recent save
public static SaveGameInfo GetContinueSaveGame();
public static SaveGameInfo LoadSaveFile(string filename, SaveGameInfo.SizeStyle sizeStyle);   // metadata/data load
public static bool SaveGameExists();  SaveGameExists(string);  GetCachedSaveGameInfo(string);
public static void DeleteSavedGame(string filename, bool removeCloudSave);
```
**SaveGameInfo** [SDK]: `.FileName`, `.MapName`, `.Difficulty`, `.RealTimestamp`, `.SaveVersion`, `.CloudState`; `static List<SaveGameInfo> CachedSaveGameInfo`; `static bool SaveGameExists()`; `static void WaitUntilSafeToSaveLoad()`; `static bool SaveCachingComplete()`; `static event OnSaveCachingComplete`; `static SaveGameInfo Load(path, SizeStyle)`. `SizeStyle { DataOnly, ... }`.

**Save DIRECTORY (patch point to redirect saves per instance):**
```csharp
SDK.GameResources.SaveGamePath        // [SDK] static string property — the save folder. Every save/load Path.Combine(SaveGamePath, filename).
SDK.GameResources.TemporaryCachePath  // [SDK] static string — temp/screenshot/zip staging
SDK.GameResources.BasePath            // [SDK] static string
SDK.GameResources.GetOverridePath(name)  // [SDK]
```
**Redirect strategy:** prefix/postfix-patch the `SDK.GameResources.SaveGamePath` getter to return a per-instance folder — this cleanly redirects ALL saves & loads for that process.

**Loading completion detection:** `SDK.GameState.IsLoading` flips false in `GameState.FinalizeLevelLoad()` [HERE]; also `SDK.GameState.OnLevelLoaded`/`OnLevelLoadedLate` events and `ScriptEvent.ScriptEvents.OnLevelLoaded`. `s_sentOnLevelLoaded` static bool [HERE].

**PersistenceManager** [SDK, static]: `SaveGame()`, `LoadGame()`, `GetLevelFilePath(sceneName)`, `LevelLoaded()`, `ClearTempData()`, `ClearPersistenceObjects()`, `MobileObjects`/`PersistentObjects` (Dictionary<GUID,ObjectPersistencePacket>), `s_tempSavePath`.

**Verdict:** Save = `GameResources.SaveGame(name, userString)`; Load = `GameResources.LoadGame(name)`; both static, directly callable. Redirect per-instance by patching `SDK.GameResources.SaveGamePath` getter. Detect load-done via `SDK.GameState.IsLoading` false-edge or postfix `FinalizeLevelLoad`. NOTE: SaveGame refuses while `InCombat`/`IsTransitionInProgress`.

---

## 9. Input  — `SDK.GameInput` [SDK, inferred]  +  `Game/GameCursor.cs` [HERE]  +  `UICamera.cs` [HERE, NGUI]

### GameInput — `SDK.GameInput` [SDK] (unqualified `GameInput`). NOT decompiled; ~70 call sites. This is the CENTRAL input wrapper — prefix-patch these statics to inject virtual input.
```csharp
GameInput.Instance                                  // singleton (MonoBehaviour)
// --- position / delta (static properties) ---
GameInput.MousePosition           // Vector2/3 screen pos (used by UIConversationManager)
GameInput.GlobalMousePosition     // Vector3
GameInput.MouseDelta              // Vector3
GameInput.WorldMousePosition      // Vector3 world-space
GameInput.WorldMousePositionOnNav // Vector3 (navmesh-projected)
// --- buttons (static methods) ---
bool GameInput.GetMouseButton(int button, bool setHandled);
bool GameInput.GetMouseButtonDown(int button, bool setHandled);
bool GameInput.GetMouseButtonUp(int button, bool setHandled);
// --- keys ---
bool GameInput.GetKeyDown(KeyCode);   GetKeyDown(KeyCode, bool setHandled);
bool GameInput.GetKeyUp(KeyCode);     GetKeyUp(KeyCode, bool setHandled);
bool GameInput.GetShiftkey();  GameInput.GetControlkey();
int  GameInput.NumberPressed;         // int property: 1-9 number-row key this frame (0 if none)
// --- mapped controls (rebindable actions) ---
bool GameInput.GetControl(MappedControl);      GetControlDown(MappedControl [,bool handle]);  GetControlUp(MappedControl);
bool GameInput.GetControlDoublePressed(MappedControl);
// --- state flags / blocking ---
bool GameInput.DisableInput      { get; set; }   // master world-input disable
bool GameInput.ClickHandled      { get; set; }   // "click already consumed this frame"
bool GameInput.SelectDead        { get; }
void GameInput.BeginBlockAllKeys();  GameInput.EndBlockAllKeys();
```
`MappedControl` [SDK] enum: `CONV_CONTINUE`, `TOGGLE_CONSOLE`, ... (rebindable). `SDK.GameState.Controls = MappedInput.DefaultMapping.Copy()` (loaded from prefs).

**Verdict — inject virtual input:** prefix-patch the `GameInput` static getters/methods to return your injected values: override `MousePosition`/`WorldMousePosition`/`GetMouseButtonDown(0,*)`/`GetKeyDown`/`NumberPressed`/`GetControlDown`. Because the whole game reads input exclusively through `GameInput.*`, patching here injects a fully virtual cursor+mouse+keyboard without touching UnityEngine.Input. This is the recommended virtual-input seam.

### GameCursor — `Game/GameCursor.cs` [HERE] : `SDK.GameCursor` (screen→world + object-under-cursor)
```csharp
public new static GameCursor Instance;
static Vector3 SDK.GameCursor.WorldPickPosition;   // [SDK] world point under cursor (used by SpawnPrefabAtMouse)
static GameObject SDK.GameCursor.GenericUnderCursor / CharacterUnderCursor / ColliderUnderCursor / UnusableUnderCursor / OverrideCharacterUnderCursor;  // [SDK] hover targets
static bool GameCursor.LockCursor { get; set; }
static CursorType GameCursor.DesiredCursor / UiCursor / ActiveCursor / CursorOverride;   // enum CursorType {None,Normal,Walk,Attack,Talk,...} [HERE]
```
Screen→world click mapping is done in the SDK cursor pick (raycast to `Walkable`/collider layers) exposed via `WorldPickPosition` + `*UnderCursor`. World clicks are consumed by `Faction.cs` (character select, L227/252), `FieldInteraction.cs`, `GAT.cs`, `Container/Door`, `InGameHUD.cs` — all reading `GameInput`.

### UICamera.cs [HERE, NGUI] — NGUI event router for UI clicks. CONFIRMED hooks:
```csharp
public static UICamera.OnCustomInput onCustomInput;   // L106 — static delegate invoked every UICamera.Update (L660-662). Feed virtual NGUI nav here.
public static bool inputHasFocus;                     // L124 — true when an NGUI UIInput has focus (text entry active). Read to know if typing.
```
IMPORTANT: `UICamera` reads **raw `UnityEngine.Input.GetKeyDown(...)` directly** for UI navigation (arrows/submit/cancel/tab/delete — L449-923), NOT `GameInput`. So to drive NGUI UI (dialogue option colliders, menus, name field) you must inject at `UnityEngine.Input` level or via `onCustomInput`; `GameInput`-level injection only covers world/gameplay input. Dialogue options are NGUI colliders routed through UICamera, but `UIConversationManager.HandleInput` reads them via `GameInput` (§3) — so the conversation option path is GameInput-driven, while generic menu nav is UnityEngine.Input-driven. Plan for BOTH input seams.

---

## 10. Character creation & level-up UI  — `UICharacterCreationManager.cs` [HERE] (global namespace) + `UICharacterCreation*` (~55 files)
```csharp
public static UICharacterCreationManager Instance => s_Instance;   // (private static s_Instance)
```
Used as a mode gate elsewhere: `if (... && !UICharacterCreationManager.Instance)` in `GameState.Update()` (L716) — i.e. `Instance` is non-null only while the creation screen exists → **use `UICharacterCreationManager.Instance != null` as "in character creation" mode detection.** New-game flow loads scene `"LifePath"` (character creation scene, see §11). Level-up shares `UICharacterCreation*` widgets (`UICharacterCreationController.cs`, `UICharacterCreationStage.cs`, `UICharacterCreationNavControl.cs`).
Name entry: `UICharacterCreationNameSetter.cs` [HERE] drives the name field via `base.Owner.Character.Name`, with `IsValidName(string)` validation and an `ErrorIndicator` shown when the name is empty/invalid (L120). **A valid non-empty name appears required to advance** (validation gate present) — so a headless "just start a game" flow must set `Character.Name` to a valid string (via the setter or directly on the player CharacterStats) rather than leaving it blank. Creation screens are normal NGUI cursor+click (BoxColliders + UICamera → but UICamera nav reads raw UnityEngine.Input, see §9). `Time.timeScale` is force-managed during creation (`UICharacterCreationEnumSetter.cs:643-646`).
Conquest/backstory: `UICharacterCreationConquestSummary.cs`, `UIConquest*` (the "Conquest" pre-game choices).
**Verdict:** Detect creation mode via `UICharacterCreationManager.Instance` non-null (and/or active scene `== "LifePath"`). Driven by normal virtual cursor+click. Whether a typed name is mandatory: name is set via `UICharacterCreationNameSetter` — inspect that file for a default/required flag; a default name is applied so a game can be started without manual text entry, but confirm by reading `UICharacterCreationNameSetter.cs` before relying on it.

---

## 11. New game / main menu

### Main menu — `UIMainMenuManager.cs` [HERE] (MonoBehaviour, global namespace)
```csharp
public static UIMainMenuManager Instance => s_instance;
public UINewGameScreen NewGameScreen;            // field
public bool MenuActive { get; set; }  MenuLocked { get; set; }
public static void StartingGame();               // plays new-game stinger, fades music
public static bool s_performCleanup;  static bool s_ReturningToMainMenuFromError;
```
Main-menu scene name = `"MainMenu"`. Menu buttons handled by `UIMainMenuClickHandler.cs` — the **New Game** button calls `UIMainMenuManager.Instance.NewGameScreen.OpenScreen()` (L148).

### Start a new game — `UINewGameScreen.cs` [HERE]
```csharp
public void OpenScreen();               // shows difficulty/mode panel
public void OnAcceptClick(GameObject go);   // reads difficulty/ToI/Expert/Legacy -> GameState.Mode, then StartIntro()
private void StartIntro();              // sets SDK.GameState.NewGame=true; GameState.Instance.PlaythroughGUID=Guid.NewGuid();
                                        //   UIMainMenuManager.StartingGame(); then UILoadingScreen.Show(Character_Creation, HandleNewGameLoadingScreenShowing)
private void HandleNewGameLoadingScreenShowing();  // => SceneManager.LoadScene("LifePath", Single)
```
**Programmatic new game:** either (a) `UIMainMenuManager.Instance.NewGameScreen.OpenScreen()` then `.OnAcceptClick(null)`, or (b) replicate `StartIntro`: set `SDK.GameState.NewGame = true`, `Game.GameState.Instance.NewGamePlusIteration = 0`, `Game.GameState.Instance.PlaythroughGUID = Guid.NewGuid()`, then `SceneManager.LoadScene("LifePath")`. Difficulty/mode set on `Game.GameState.Mode` (GameMode) before load.

### Return to main menu (episode reset) — `Game/GameState.cs` [HERE]
```csharp
public static void GameState.LoadMainMenu(bool fadeOut);   // clean path (Trial-of-Iron save if needed, fade, SceneManager.LoadScene("MainMenu"))
public override void ReturnToMainMenuFromError();          // error path
```
**Verdict:** New game = drive `UINewGameScreen` or replicate `StartIntro` + `LoadScene("LifePath")`. Return to menu = `Game.GameState.LoadMainMenu(true/false)`. `UIMainMenuManager.Instance` gates menu state.

---

## 12. Debug console  — `Game/CommandLine.cs` [HERE] : `SDK.CommandLine`  +  `UICommandLine.cs` / `UIConsole*` [HERE]

**Command dispatcher / programmatic invocation:**
```csharp
CommandLine.RunCommand(string text);   // [SDK.CommandLine, static] <-- PARSES + DISPATCHES a console command line.
                                        //   Called by UICommandLine.OnSubmit() with the typed string.
```
`UICommandLine.cs` [HERE] is the input box: opened via `GameInput.GetControlDown(MappedControl.TOGGLE_CONSOLE, handle:true)`; on submit calls `CommandLine.RunCommand(text)`. **To run any console command programmatically (e.g. `"reputationaddpoints SK_GravenAshe favor 8"`), call `SDK.CommandLine.RunCommand("<command args>")`.** `reputationaddpoints` is implemented in **`Scripts.cs` [HERE]** (the script-function library that console commands and dialogue scripts share) — confirmed the only match for that token. So RunCommand resolves the command name to the `Scripts.cs` method by reflection. You can also call the `Scripts.cs` rep method directly if you locate its exact signature there.

**`Game.CommandLine` static command methods** (many tagged `[Cheat]`) — directly callable, examples [HERE]:
`ResetParty()`, `Damage(string)`, `Difficulty(string)`, `ChallengeMode(string)`, `AddItem(string,string)`, `AttributeScore(name,attr,val)`, `Skill(name,skill,val)`, `AddAbility/RemoveAbility`, `SetTime(string)`, `AdvanceDay()`, `Edict(tag)`/`RemoveEdict()`/`LearnEdictPackage(tag)`, `AddBelief/SpendBelief`, `AddCompanion(name)`/`AddAllCompanions()`, `SpawnPrefabAtMouse(...)`, `UnlockAllMaps()`, `UnlockBestiary()`, `ManageParty()`, `EvadeAll()`.
**Cheat toggle:** `public new static void IRoll20s()` [HERE] — flips `SDK.GameState.CheatsEnabled` (disables achievements). Many `[Cheat]` commands require cheats enabled.

**Console output** — `SDK.Console` [SDK] (unqualified `Console`): `Console.AddMessage(string)`, `AddMessage(string, Color)`, `AddMessage(string, Console.ConsoleState)`, `AddMessage(string title, string body, Color)`; `Console.Format(fmt, args...)` -> string; `Console.ConsoleState` enum { DIALOG_BIG, DEBUG, ... }; `Console.Instance`. UI: `UIConsole.cs`, `UIConsoleEntry.cs`, `UIConsoleText.cs` [HERE].

**Verdict:** Invoke any command via `SDK.CommandLine.RunCommand("...")` (single reflection call). For typed helpers, call `Game.CommandLine.<Method>()` statics directly. Enable cheats with `Game.CommandLine.IRoll20s()` (or set `SDK.GameState.CheatsEnabled = true`).

---

## Extras (incidental findings)

### Edict / timer mechanics — `Game/EdictManager.cs` [HERE], `Game/Edict.cs` [HERE]
```csharp
EdictManager.Instance;                                  // static field (MonoBehaviour)
Edict GetActiveEdict();  Edict GetActiveEdict(Region);  // active edict for current/given region
EdictPackage GetEdictPackageByTag(string);  Edict GetEdictByTag(string);
void ActivateEdictPackage(Region, EdictPackage);  ActivateEdictPackage(string regionTag, string edictPackageTag);
void DeactivateEdict(Region/string);   void LearnEdictPackage(string/EdictPackage);
bool IsEdictPackageActive(string tag);  bool IsEdictPackageKnown(...);
static event EventHandler EdictPreActivated / EdictPostActivated / EdictPreDeactivated / EdictPostDeactivated;  // subscribe for edict events
```
`Edict` [HERE]: `.Tag`, `.EdictNameText/Description/BreakText` (DatabaseString), `Activate()`/`Deactivate()`, `getBreakVar()` (reads GlobalVariables). "Day of Swords" is a scripted date/global, tracked via `WorldTime` + `GlobalVariables` + `AchievementTracker.TrackedAchievementStat.HasDayOfSwordsArrive...`; no dedicated countdown class.

### Area transition events
`SDK.GameState.LevelUnload` / `LevelLoaded` (EventHandler events, subscribed in EdictManager). `SDK.GameState.OnLevelLoadedEarly/OnLevelLoaded/OnLevelLoadedLate(levelName, EventArgs)`. `ScriptEvent.BroadcastEvent(ScriptEvent.ScriptEvents.OnSceneExited / OnLevelLoaded)`. `GameState.ChangeLevel(MapData/MapType/string)` initiates transitions.

### Party enumeration — `SDK.PartyMemberAI` [SDK] statics (used everywhere) + `Game/PartyMemberAI.cs` [HERE]
```csharp
static SDK.PartyMemberAI[] PartyMembers;              // fixed array (MAX_PARTY_MEMBERS), null slots => empty
static List<SDK.PartyMemberAI> OnlyPrimaryPartyMembers;   // active primary members
static GameObject[] SelectedPartyMembers;             // currently player-selected (for commands)
static int MAX_PARTY_MEMBERS; MAX_PRIMARY_PARTY_MEMBERS=4; MAX_SECONDARY_SLOTS=4;
static int NextAvailablePrimarySlot;
static void PartyMemberAI.AddToActiveParty(GameObject, bool fromScript);   // [HERE]
static void PartyMemberAI.RemoveFromActiveParty(PartyMemberAI);            // [HERE]
static void PartyMemberAI.PopAllStates();  static void Reset();
bool  partyMember.Selected { get; set; }              // [SDK] selection state (per member)
int   .Slot / .AssignedSlot;  bool .IsActiveInParty;  bool .IsAdventurer;   // [HERE]
FactionName .ReputationFaction;                        // [HERE] links companion to Reputation
```
`Game.Player : PartyMemberAI`-ish uses `IsSelected` (Player.cs). Iterate `SDK.PartyMemberAI.PartyMembers` (skip nulls) for the party; `SelectedPartyMembers` for current selection.

### Per-character health — `Game/Health.cs` [HERE] : `SDK.Health`  (RequireComponent CharacterStats)
```csharp
float base.CurrentHealth { get; set; }   // [SDK] current HP (Health is the HP component)
float base.MaxHealth      { get; }        // [SDK] max HP
// Game-layer: m_stats (CharacterStats), DerivedMaxHealth via CharacterStats.DerivedMaxHealth
enum Health.DeathStatusType { INVALID=-1, KO, Death };
static bool Health.BloodyMess;  static void Health.ResetCharacter(GameObject);
void ApplyHealthChangeDirectly(float delta, bool applyIfDead);
OnyxEvent<GameObject,GameEventArgs> OnWouldHaveKilled / OnPartyWouldHaveKilled;
```
Get HP: `go.GetComponent<Game.Health>().CurrentHealth / .MaxHealth`.

### CharacterStats — `Game/CharacterStats.cs` [HERE] : `SDK.CharacterStats`
`GameState.s_playerCharacter.Character` is the player's CharacterStats. Members seen: `DerivedMaxHealth`, `Level`, `ActiveAbilities` (List<GenericAbility>), `Name()`, `NameColored(GameObject)` (static), `DisplayName`, `Gender`, `SetBaseAttributeScore(AttributeScoreType,int)`, skill props (`StealthSkill`, `LoreSkill`, ... `MechanicsSkill`), enums `AttributeScoreType`, `SkillType`, `SkillCategory`. Static `SDK.CharacterStats.Name(GameObject)`, `GetGender(...)`.

### Position / selection
Position = standard `component.transform.position` (Unity). Selection = `PartyMemberAI.Selected` / `SelectedPartyMembers` (above). Under-cursor character = `SDK.GameCursor.CharacterUnderCursor` (§9).

---

## Harmony targeting cheat-sheet
| Need | Target | Kind |
|---|---|---|
| Combat on/off events | `SDK.GameState.OnCombatStart/OnCombatEnd` | subscribe event |
| Read combat/loading/gameover | `SDK.GameState.InCombat/IsLoading/GameOver` | read static |
| Area-load finished | `Game.GameState.FinalizeLevelLoad` | postfix |
| Intercept option text | `Conversation.GetNodeText` | postfix (swap) |
| Shuffle option order | `Conversation.GetResponseNodes` | postfix (reorder list) |
| Which option chosen / inject choice | `UIConversationManager.PlayerInput(int)` | postfix / call |
| Favor/wrath stream | `Game.ReputationManager.AddReputation`/`RemoveReputation` | postfix |
| Read favor/wrath | `ReputationManager.Instance.GetReputation((int)FactionName.X).PositiveAxisValue/GoodRank` | read |
| Quest milestones | `QuestManager.Instance.OnQuestAdvanced` / `CompleteQuest` | subscribe / postfix |
| Global-var mutations | `SDK.GlobalVariables.SetVariable(string,int)` | postfix |
| Inject virtual input | `SDK.GameInput.*` static getters/methods | prefix (return injected) |
| Game speed / pause | `TimeController.Instance` props / patch timeScale setter | set / prefix |
| Save / load | `GameResources.SaveGame` / `LoadGame` | call |
| Redirect save dir | `SDK.GameResources.SaveGamePath` getter | prefix/postfix |
| Run console command | `SDK.CommandLine.RunCommand(string)` | call |
| New game | `UINewGameScreen` OpenScreen/OnAcceptClick or replicate StartIntro + LoadScene("LifePath") | call |
| To main menu | `Game.GameState.LoadMainMenu(bool)` | call |
| In char-creation? | `UICharacterCreationManager.Instance != null` | read |

## Open items to confirm against `Assembly-CSharp-firstpass.dll` (SDK)
- Exact signatures/visibility of: `SDK.GlobalVariables.GetVariable/SetVariable`, all `SDK.GameInput` members, `SDK.TimeController` timeScale-writing property, `SDK.Console.AddMessage` overloads, `SDK.CommandLine.RunCommand` + how `reputationaddpoints` is registered, `SDK.Reputation.PositiveAxisValue/GoodRank` getters, `SDK.GameResources.SaveGamePath` getter.
- `UICamera.cs` (present here) static input-override delegates (`onCustomInput` / `GetKeyDown`) if feeding NGUI directly.
- `UICharacterCreationNameSetter.cs` — whether a default name is auto-applied (name mandatory?).
