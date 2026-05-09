---
name: desktop-framework
description: Choose the right desktop framework and scaffold a production project structure. Use at the START of any desktop app project. Triggers on: "build a desktop app", "Electron app", "Tauri app", "desktop application", "cross-platform app", "native app", "scaffold desktop project".
---

Resolve the framework in one pass. Scaffold the full project. Ship no boilerplate theater.

## Framework Decision Tree (resolve before writing one line of code)

```
Need maximum native performance + small bundle?   → Tauri (Rust backend + WebView)
Large team, web devs, rich ecosystem?             → Electron (Node backend + Chromium)
Python-first team?                                → PyQt6 / PySide6 (Qt bindings)
Truly native UI required (macOS/Windows)?         → Swift (macOS) / WinUI 3 (Windows)
Simple utility, single platform?                  → Tauri (macOS/Windows) or PyQt6
Need .NET ecosystem / Windows-primary?            → .NET MAUI or WPF (Windows-only)
```

**Default: Tauri** for new projects. Smaller binary (~3MB vs ~150MB Electron), lower RAM, Rust security model.
**Use Electron** when team is JS-only or when Node.js native modules are required.

---

## Tauri Project Structure (default)

```
my-app/
├── src-tauri/
│   ├── src/
│   │   ├── main.rs          # Entry point, window config
│   │   ├── commands.rs      # IPC command handlers
│   │   ├── state.rs         # App-wide state (Mutex-wrapped)
│   │   └── db.rs            # SQLite via rusqlite
│   ├── Cargo.toml
│   └── tauri.conf.json      # App identity, window, permissions
├── src/                     # Frontend (React/Svelte/Vue)
│   ├── App.tsx
│   ├── components/
│   ├── hooks/               # useCommand() wrappers for IPC
│   └── stores/              # Zustand / Svelte stores
├── package.json
└── vite.config.ts
```

**tauri.conf.json essentials:**
```json
{
  "productName": "MyApp",
  "version": "1.0.0",
  "identifier": "com.company.myapp",
  "app": {
    "windows": [{ "title": "MyApp", "width": 1200, "height": 800, "minWidth": 800, "minHeight": 600 }]
  },
  "bundle": { "active": true, "targets": "all" },
  "security": { "csp": "default-src 'self'; script-src 'self'" }
}
```

---

## Electron Project Structure

```
my-app/
├── main/                    # Main process (Node.js)
│   ├── index.ts             # BrowserWindow creation
│   ├── ipc.ts               # ipcMain handlers
│   ├── menu.ts              # App menu
│   └── preload.ts           # contextBridge exposure
├── renderer/                # Renderer process (React/Vue)
│   ├── App.tsx
│   ├── components/
│   └── stores/
├── shared/                  # Types shared across processes
│   └── types.ts
├── electron-builder.yml     # Packaging config
└── package.json
```

**Security non-negotiable (Electron):**
```typescript
// main/index.ts
const win = new BrowserWindow({
  webPreferences: {
    nodeIntegration: false,        // NEVER true
    contextIsolation: true,        // ALWAYS true
    sandbox: true,
    preload: path.join(__dirname, 'preload.js'),
  }
});
```

---

## PyQt6 Structure

```
my-app/
├── main.py                  # QApplication entry
├── ui/
│   ├── main_window.py       # QMainWindow subclass
│   ├── dialogs/
│   └── widgets/             # Custom QWidget subclasses
├── core/                    # Business logic (no Qt imports)
│   ├── services/
│   └── models/
├── resources/               # Icons, .qrc files
└── requirements.txt
```

---

## Universal Project Rules

**Entry point must:**
- Set app name, version, icon
- Handle single-instance lock (prevent duplicate windows)
- Set up crash reporter / error boundary before window creation
- Load user preferences before first render

**Environment config:**
```
.env.development    → dev API URLs, verbose logging, DevTools open
.env.production     → prod URLs, error-only logging, no DevTools
```

**First files to create in order:**
1. Framework config (`tauri.conf.json` / `electron-builder.yml`)
2. Entry point (`main.rs` / `main/index.ts` / `main.py`)
3. IPC bridge (commands/preload)
4. Frontend shell (`App.tsx` with router)
5. State store

## Output Order

1. **Framework choice** (one line justification)
2. **Directory tree** (full, copy-paste ready)
3. **Entry point** code
4. **Framework config file** (tauri.conf.json / electron-builder.yml)
5. **IPC bridge stub**
6. **Frontend App shell**
