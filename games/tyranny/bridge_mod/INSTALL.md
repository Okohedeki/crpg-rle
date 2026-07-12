# Bridge mod installation (Tyranny + BepInEx 5.4.22)

1. Install [BepInEx 5.4.22 x64](https://github.com/BepInEx/BepInEx/releases/tag/v5.4.22) into the Tyranny game root (the folder containing `Tyranny.exe`): extract so `winhttp.dll`, `doorstop_config.ini`, and `BepInEx/` sit next to the exe.

2. Run the game once so `BepInEx/config/BepInEx.cfg` is generated, then **make two required edits** to that file:

   ```ini
   [Chainloader]
   ## The Pillars engine destroys unknown root GameObjects on scene load,
   ## which kills the plugin (and its IPC server) silently at startup.
   HideManagerGameObject = true

   [Preloader.Entrypoint]
   ## With the default Application entrypoint, the chainloader loads the game
   ## assemblies before Unity's MonoManager does. On this Unity 5.4 build that
   ## breaks script binding on the Global prefab ("The referenced script on
   ## this Behaviour is missing!"), leaving the game stuck on SplashScreen
   ## with save-loading broken. Camera..cctor fires after Unity has loaded
   ## the game assemblies itself.
   Type = Camera
   ```

   Both symptoms and root causes are documented in `tools/decompile_notes.md` history.

3. Build the plugin and copy it in:

   ```
   dotnet build games/tyranny/bridge_mod/src/CRPGBridge/CRPGBridge.csproj -c Release
   copy games\tyranny\bridge_mod\src\CRPGBridge\bin\Release\net35\CRPGBridge.dll "<GameDir>\BepInEx\plugins\"
   ```

   If your game is not at `C:\Program Files (x86)\Steam\steamapps\common\Tyranny`, pass `-p:GameDir="<path>"` or set the `CRPG_GAME_DIR` environment variable.

4. Verify: launch `Tyranny.exe` and check `BepInEx/LogOutput.log` contains
   `CRPG Bridge ... IPC listening on 127.0.0.1:5555` and
   `[input] icall patches: 9 ok, 0 failed`.

Environment variables read by the plugin per instance: `CRPG_INSTANCE_ID` (default 0), `CRPG_BRIDGE_PORT` (default 5555 + instance id).
