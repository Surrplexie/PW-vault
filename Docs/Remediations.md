Dev logs rules; REM-1, REM-2 any of these terms are the new 'updates' like "Update 1", all major logs entered here. Note; REM-1.2, REM-1.4 etc. are only for GitHub commits and pushing, never named here.

## REM-1

## REM-2

## REM-3

**AutoFill HUD — render fix, login-page matching, address-bar URL detection** (2026-06-08)

### Problem
- HUD appeared as a blank dark square (top-left) with no labels or Fill buttons.
- Matching worked on main site pages (e.g. `pokemon.com/us`) but failed on login/SSO pages (e.g. `access.pokemon.com/login`, `accounts.paradoxplaza.com`) where the tab title is only a page name like “Pokémon Trainer Central”.
- Weak fuzzy matches (Patreon, wemod) appeared alongside correct entries on some domains.

### Root causes
1. Invalid Tk geometry string (`340+1562+60` instead of `WIDTHxHEIGHT+X+Y`) — window created at default tiny size with no room for widgets.
2. Domain detection relied on tab title only; login pages rarely include the hostname.
3. Unicode in titles (`Pokémon`) did not match ASCII vault entries (`pokemon.com`).
4. Fuzzy score floor was too low, allowing unrelated vault entries through.

### Changes
- **`autofill_hud.py`**
  - Fixed HUD sizing via `_place_window()` — proper `WxH+X+Y` after `update_idletasks()`.
  - Rebuilt match scoring: `_normalize()`, `_page_tokens()`, `_entry_names()`, subdomain/partial name matching.
  - `MIN_SCORE = 0.60` to drop weak false positives.
  - ASCII-safe UI labels (removed emoji/special chars that failed in some builds).
- **`browser_watch.py`**
  - Strip browser suffix (`- Brave`, `- Chrome`, etc.) before title parsing.
  - `_resolve_domain()` prefers address-bar hostname over tab title.
  - URL result cached per `(hwnd, title)` to limit UI Automation polling.
- **`browser_url.py`** *(new)*
  - Windows: read omnibox URL via `uiautomation` (`Address and search bar`).
  - `hostname_from_url()` — strips scheme, path, and query tokens (`?login_challenge=…` ignored).
- **`requirements.txt`** — `uiautomation>=2.0.18` (Windows only).
- **`build_exe.bat`** — PyInstaller hidden imports for `uiautomation` / `comtypes`.

### Behaviour after fix
| Context | Detected as | Matches `pokemon.com` entry |
|---|---|---|
| `pokemon.com/us` (title contains domain) | `pokemon.com` | Yes (100%) |
| `access.pokemon.com/login?…` (URL only) | `access.pokemon.com` | Yes (85%, subdomain) |
| `Welcome to Paradox - Brave` (title only) | `welcome to paradox` | Yes (`paradox.com`) |
| `Pokémon Trainer Central` (unicode title) | normalized → `pokemon` token | Yes |

### Build / run notes
```bat
pip install -r requirements.txt
python main.py
```
or `build_exe.bat` for `dist\VaultPass.exe`. Windows autofill URL detection requires `uiautomation`; without it, title-only matching still works but login pages are less reliable.

### Files touched
`autofill_hud.py`, `browser_watch.py`, `browser_url.py`, `requirements.txt`, `build_exe.bat`

## REM-4

**Atomic vault saves + `.bak` rotation** (2026-06-21)

### Problem
- `_autosave_silent()` wrote encrypted bytes directly to the vault path (`write_bytes`).
- A crash or power loss mid-write could truncate or corrupt the only on-disk copy of the vault.

### Changes
- **`vault_crypto.py`**
  - `save_vault_blob()` — write to a same-directory temp file, `fsync`, copy previous vault to `<name>.bak`, then `os.replace()` into place (with brief retries on Windows file-lock races).
  - `vault_backup_path()` — helper for the single rotating backup filename.
  - Removed unused `hashlib` import.
- **`main.py`** — `_autosave_silent()` now calls `save_vault_blob()` instead of direct `write_bytes`.
- **`.gitignore`** — ignore `*.vpm.bak` alongside `*.vpm`.
- **`tests/test_vault_crypto.py`** — round-trip crypto, backup rotation, and failed-replace cleanup.

### Behaviour after fix
| Scenario | Result |
|---|---|
| First save (new vault) | Atomic write; no `.bak` created |
| Subsequent saves | Previous vault copied to `!vault.vpm.bak`, then new blob replaces `!vault.vpm` atomically |
| Crash during write | Temp file may remain; existing `.vpm` (and `.bak` if present) stay intact |

### Build / run notes
```bat
pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py
```

### Files touched
`vault_crypto.py`, `main.py`, `.gitignore`, `tests/test_vault_crypto.py`

## REM-2

## REM-3

## REM-4

## REM-5

## REM-3

## REM-4

## REM-5

## REM-6

## REM-4

## REM-5

## REM-6

## REM-7

## REM-5

## REM-6

## REM-7

## REM-8

## REM-6

## REM-7

## REM-8

## REM-9

## REM-7

## REM-8

## REM-9

## REM-10

## REM-8

## REM-9

## REM-10

## REM-11

## REM-9

## REM-10

## REM-11

## REM-12

## REM-10

## REM-11

## REM-12

## REM-13

## REM-11

## REM-12

## REM-13

## REM-14

## REM-12

## REM-13

## REM-14

## REM-15

## REM-13

## REM-14

## REM-15

## REM-16

## REM-14

## REM-15

## REM-16

## REM-17

## REM-15

## REM-16

## REM-17

## REM-18

## REM-16

## REM-17

## REM-18

## REM-19

## REM-17

## REM-18

## REM-19

## REM-20

## REM-18

## REM-19

## REM-20

## REM-21

## REM-19

## REM-20

## REM-21

## REM-22

## REM-20

## REM-21

## REM-22

## REM-23

## REM-21

## REM-22

## REM-23

## REM-24

## REM-22

## REM-23

## REM-24

## REM-25

## REM-23

## REM-24

## REM-25

## REM-26

## REM-24

## REM-25

## REM-26

## REM-27

## REM-25

## REM-26

## REM-27

## REM-28

## REM-26

## REM-27

## REM-28

## REM-29

## REM-27

## REM-28

## REM-29

## REM-30

## REM-28

## REM-29

## REM-30

## REM-31

## REM-29

## REM-30

## REM-31

## REM-32

## REM-30

## REM-31

## REM-32

## REM-33

## REM-31

## REM-32

## REM-33

## REM-34

## REM-32

## REM-33

## REM-34

## REM-35

## REM-33

## REM-34

## REM-35

## REM-36

## REM-34

## REM-35

## REM-36

## REM-37

## REM-35

## REM-36

## REM-37

## REM-38

## REM-36

## REM-37

## REM-38

## REM-39

## REM-37

## REM-38

## REM-39

## REM-40

## REM-38

## REM-39

## REM-40

## REM-41

## REM-39

## REM-40

## REM-41

## REM-42

## REM-40

## REM-41

## REM-42

## REM-43

## REM-41

## REM-42

## REM-43

## REM-44

## REM-42

## REM-43

## REM-44

## REM-45

## REM-43

## REM-44

## REM-45

## REM-46

## REM-44

## REM-45

## REM-46

## REM-47

## REM-45

## REM-46

## REM-47

## REM-48

## REM-46

## REM-47

## REM-48

## REM-49

## REM-47

## REM-48

## REM-49

## REM-50

## REM-48

## REM-49

## REM-50

## REM-51

## REM-49

## REM-50

## REM-51

## REM-52

## REM-50

## REM-51

## REM-52

## REM-53

## REM-51

## REM-52

## REM-53

## REM-54

## REM-52

## REM-53

## REM-54

## REM-55

## REM-53

## REM-54

## REM-55

## REM-56

## REM-54

## REM-55

## REM-56

## REM-57

## REM-55

## REM-56

## REM-57

## REM-58

## REM-56

## REM-57

## REM-58

## REM-59

## REM-57

## REM-58

## REM-59

## REM-60

## REM-58

## REM-59

## REM-60

## REM-61

## REM-59

## REM-60

## REM-61

## REM-62

## REM-60

## REM-61

## REM-62

## REM-63

## REM-61

## REM-62

## REM-63

## REM-64

## REM-62

## REM-63

## REM-64

## REM-65

## REM-63

## REM-64

## REM-65

## REM-66

## REM-64

## REM-65

## REM-66

## REM-67

## REM-65

## REM-66

## REM-67

## REM-68

## REM-66

## REM-67

## REM-68

## REM-69

## REM-67

## REM-68

## REM-69

## REM-70

## REM-68

## REM-69

## REM-70

## REM-71

## REM-69

## REM-70

## REM-71

## REM-72

## REM-70

## REM-71

## REM-72

## REM-73

## REM-71

## REM-72

## REM-73

## REM-74

## REM-72

## REM-73

## REM-74

## REM-75

## REM-73

## REM-74

## REM-75

## REM-76

## REM-74

## REM-75

## REM-76

## REM-77

## REM-75

## REM-76

## REM-77

## REM-78

## REM-76

## REM-77

## REM-78

## REM-79

## REM-77

## REM-78

## REM-79

## REM-80

## REM-78

## REM-79

## REM-80

## REM-81

## REM-79

## REM-80

## REM-81

## REM-82

## REM-80

## REM-81

## REM-82

## REM-83

## REM-81

## REM-82

## REM-83

## REM-84

## REM-82

## REM-83

## REM-84

## REM-85

## REM-83

## REM-84

## REM-85

## REM-86

## REM-84

## REM-85

## REM-86

## REM-87

## REM-85

## REM-86

## REM-87

## REM-88

## REM-86

## REM-87

## REM-88

## REM-89

## REM-87

## REM-88

## REM-89

## REM-90

## REM-88

## REM-89

## REM-90

## REM-91

## REM-89

## REM-90

## REM-91

## REM-92

## REM-90

## REM-91

## REM-92

## REM-93

## REM-91

## REM-92

## REM-93

## REM-94

## REM-92

## REM-93

## REM-94

## REM-95

## REM-93

## REM-94

## REM-95

## REM-96

## REM-94

## REM-95

## REM-96

## REM-97

## REM-95

## REM-96

## REM-97

## REM-98

## REM-96

## REM-97

## REM-98

## REM-99

## REM-97

## REM-98

## REM-99

## REM-100

## REM-98

## REM-99

## REM-100

## REM-101

## REM-99

## REM-100

## REM-101

## REM-102

## REM-100

## REM-101

## REM-102

## REM-103

## REM-101

## REM-102

## REM-103

## REM-104

## REM-102

## REM-103

## REM-104

## REM-105

## REM-103

## REM-104

## REM-105

## REM-106

## REM-104

## REM-105

## REM-106

## REM-107

## REM-105

## REM-106

## REM-107

## REM-108

## REM-106

## REM-107

## REM-108

## REM-109

## REM-107

## REM-108

## REM-109

## REM-110

## REM-108

## REM-109

## REM-110

## REM-111

## REM-109

## REM-110

## REM-111

## REM-112

## REM-110

## REM-111

## REM-112

## REM-113

## REM-111

## REM-112

## REM-113

## REM-114

## REM-112

## REM-113

## REM-114

## REM-115

## REM-113

## REM-114

## REM-115

## REM-116

## REM-114

## REM-115

## REM-116

## REM-117

## REM-115

## REM-116

## REM-117

## REM-118

## REM-116

## REM-117

## REM-118

## REM-119

## REM-117

## REM-118

## REM-119

## REM-120

## REM-118

## REM-119

## REM-120

## REM-121

## REM-119

## REM-120

## REM-121

## REM-122

## REM-120

## REM-121

## REM-122

## REM-123

## REM-121

## REM-122

## REM-123

## REM-124

## REM-122

## REM-123

## REM-124

## REM-125

## REM-123

## REM-124

## REM-125

## REM-126

## REM-124

## REM-125

## REM-126

## REM-127

## REM-125

## REM-126

## REM-127

## REM-128

## REM-126

