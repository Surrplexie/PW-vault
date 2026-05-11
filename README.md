# VaultPass

**VaultPass** is a fully offline, single-file password manager for Windows. It stores passwords, payment cards, addresses, login groups, and images — all encrypted locally on your machine. No cloud. No accounts. No telemetry.

> **Personal-use software.** VaultPass is built and maintained for personal use. It is shared as-is, with no guarantees of fitness for any particular purpose. See the [Legal Disclaimer](#legal-disclaimer) and [License](#license) sections before use.

---

## Table of Contents

- [Features](#features)
- [Download & Install](#download--install)
- [Running from Source](#running-from-source)
- [Building the Executable](#building-the-executable)
- [Usage Guide](#usage-guide)
  - [Creating / Opening a Vault](#creating--opening-a-vault)
  - [Passwords Tab](#passwords-tab)
  - [Cards Tab](#cards-tab)
  - [Addresses Tab](#addresses-tab)
  - [Login Via Tab](#login-via-tab)
  - [Images Tab](#images-tab)
  - [Search Syntax](#search-syntax)
  - [Autofill HUD](#autofill-hud)
- [Vault File](#vault-file)
- [Security Model](#security-model)
- [Legal Disclaimer](#legal-disclaimer)
- [License](#license)

---

## Features

| Category | Details |
|---|---|
| **Encryption** | PBKDF2-HMAC-SHA256 (480,000 iterations) + Fernet symmetric encryption |
| **Vault format** | Single `.vpm` binary file — fully portable |
| **Tabs** | Passwords, Cards, Addresses, Login Via, Images |
| **Autofill** | Browser-aware overlay HUD — pastes directly into the focused field without stealing focus |
| **Browser detection** | Chrome, Edge, Brave, Opera GX, Firefox, Waterfox (via Win32 ctypes, no extra installs) |
| **Search** | Advanced query syntax with field filters, AND/OR/NOT, wildcards |
| **Clipboard safety** | Clipboard auto-clears 30 seconds after copying a sensitive value |
| **Offline** | Zero network access — everything stays on your machine |
| **Single executable** | One `.exe` — no installer, no Python required |

---

## Download & Install

Pre-built Windows executables are available on the [**Releases page**](https://github.com/Surrplexie/PW-vault/releases).

1. Go to [https://github.com/Surrplexie/PW-vault/releases](https://github.com/Surrplexie/PW-vault/releases)
2. Under the latest release, download **`VaultPass.exe`**
3. Place `VaultPass.exe` in any folder you choose — it is fully self-contained
4. Double-click to run; no installation is needed

> **Note:** Windows Defender or SmartScreen may flag an unsigned executable downloaded from the web. This is expected for unsigned personal-use software. You can right-click → **Properties** → **Unblock**, or click **More info → Run anyway** in SmartScreen, if you trust the source.

Your vault file (`!vault.vpm`) will be created in the **same folder as the executable** the first time you save.

---

## Running from Source

**Requirements:** Python 3.11+, Windows

```bash
# 1. Clone the repository
git clone https://github.com/Surrplexie/PW-vault.git
cd PW-vault

# 2. (Optional) create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

`requirements.txt` contains:
```
cryptography>=42.0.0
Pillow>=10.0.0
```

---

## Building the Executable

A convenience script is included to build a single-file Windows executable using PyInstaller.

```bat
build_exe.bat
```

This runs:
```bat
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --windowed --name VaultPass --clean main.py
```

The finished executable will be at `dist\VaultPass.exe`.

---

## Usage Guide

### Creating / Opening a Vault

- On first launch, VaultPass will prompt you to **set a master password** and create a new vault.
- On subsequent launches, you enter your master password to **unlock** the existing vault.
- You can also **open a different vault file** from the File menu, or keep multiple `.vpm` files in different folders each opened by a separate copy of the executable.

> There is no password recovery. If you forget your master password, your vault data is unrecoverable. Keep your master password somewhere safe.

---

### Passwords Tab

Each password entry contains the following fields:

| Field | Notes |
|---|---|
| Website Login Using | The site or service name |
| Account Type | e.g. Personal, Work, Gaming |
| Website Username | Your login username |
| Website Password | Masked by default — click to reveal |
| Website Email | Email used to register |
| Website Phone Number | Linked phone number |
| Acc Sec. — 2FA | TOTP app, SMS, or hardware key info |
| Acc Sec. — Phrase/Seed | Recovery or seed phrase (sensitive) |
| Acc Sec. — Linked Accounts | OAuth or SSO connections |
| Acc Sec. — Extended Recovery | Backup codes, security questions |
| Add. Data. — Slot A/B/C | Free-form extra fields |

Sensitive fields (password, phrase, recovery, etc.) are masked and clipboard-cleared automatically after 30 seconds.

---

### Cards Tab

Stores payment card details:

- Card name (e.g. "Chase Debit")
- Card type: Debit / Credit / Prepaid / Gift / Other
- Card number (displayed grouped and masked by default)
- Expiry, CVV, PIN
- Issuing bank
- Notes

---

### Addresses Tab

Stores physical addresses with labels (Home, Work, Billing, etc.):

- Street address lines 1 & 2
- City, State/Province, Postal code, Country
- Notes

---

### Login Via Tab

Groups accounts that share a login provider (e.g. "Login with Google"). Useful for tracking which services use a single SSO identity.

---

### Images Tab

Stores images directly inside the encrypted vault (e.g. photos of IDs, insurance cards). Images are base64-encoded into the vault file. A warning is shown for images larger than 1 MB to keep vault size reasonable.

---

### Search Syntax

VaultPass includes a powerful search engine. Type queries into the search bar on any tab.

| Syntax | Meaning |
|---|---|
| `github` | Substring match anywhere |
| `"my exact phrase"` | Literal phrase (with spaces) |
| `domain:github` | Match only in the site domain |
| `email:gmail` | Match in the email field |
| `pass:hunter` | Match in password field |
| `2fa:yes` | Match in 2FA field |
| `field:*` | Field has a real value (not empty/NULL) |
| `-word` | Exclude entries matching word (NOT) |
| `NOT word` | Same as `-word` |
| `word1 word2` | AND — both must match |
| `word1 OR word2` | OR — either must match |
| `word1 \| word2` | Same as OR |

**Field aliases:**

`domain` / `site` / `url` · `email` / `mail` · `user` / `username` / `login` · `pass` / `pw` / `password` · `phone` · `2fa` / `mfa` / `otp` · `phrase` / `seed` · `recovery` · `type` · `linked` · `slot` / `slot-a` / `slot-b` / `slot-c`

**Examples:**
```
pass:* -2fa:yes          → has a password AND does not have 2FA set
domain:git email:me      → site contains "git" AND email contains "me"
github OR gitlab         → either domain
```

---

### Autofill HUD

When you switch to a browser window with a recognized domain, a small floating overlay appears near your cursor:

- Shows up to 3 matching vault entries, ranked by domain similarity
- Displays Username, Email, Password, and Phone (if set)
- Click **Fill** to paste the value directly into the focused browser input field — without stealing focus from the browser
- The overlay auto-hides after **20 seconds** of no interaction
- The header bar can be dragged to reposition it

**Supported browsers:** Chrome, Edge, Brave, Opera GX, Vivaldi, Firefox, Waterfox, Librewolf

---

## Vault File

| Detail | Value |
|---|---|
| Default filename | `!vault.vpm` |
| Default location | Same folder as `VaultPass.exe` (or `main.py` when running from source) |
| Format | Binary: `VAULT1` header + 16-byte random salt + Fernet-encrypted JSON |
| Extension | `.vpm` (VaultPass Module) |

You can back up your vault by simply copying the `.vpm` file. The file is encrypted and safe to store on a USB drive, cloud folder, etc. — it cannot be read without your master password.

> `.vpm` files are excluded from version control by `.gitignore` — your vault will never be accidentally committed to a repository.

---

## Security Model

- **Key derivation:** PBKDF2-HMAC-SHA256 with 480,000 iterations and a 16-byte random salt per save
- **Encryption:** Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library
- **Salt:** Re-generated on every save — each saved file has a unique salt
- **No master password storage:** The password is never written to disk in any form; it only exists in memory for the duration of the session
- **Clipboard:** Sensitive values are automatically purged from the clipboard 30 seconds after copying
- **No network:** VaultPass makes zero outbound network requests

**Limitations to be aware of:**
- VaultPass does not protect against keyloggers, malware, or a compromised OS — it is only as secure as your machine
- There is no two-factor authentication on the vault itself
- Clipboard injection during the 30-second window is possible if malware is present

---

## Legal Disclaimer

> **READ BEFORE USE**
>
> VaultPass is personal-use software provided **"as is"**, without warranty of any kind, express or implied. The author, **Surrplexie**, makes **no representations or warranties** regarding the accuracy, reliability, completeness, or suitability of this software for any purpose.
>
> **By downloading or using VaultPass, you agree that:**
>
> - Surrplexie is **not responsible** for any loss of data, loss of access, corruption of vault files, security breaches, financial loss, or any other direct, indirect, incidental, special, or consequential damages arising from the use or inability to use this software.
> - This software is intended **strictly for personal use**. It is **not audited**, **not certified**, and **not recommended** for securing sensitive organizational, financial, medical, or legal data in a professional capacity.
> - You are solely responsible for keeping your master password secure. **There is no password reset or account recovery.** Lost passwords mean permanently lost data.
> - Surrplexie provides **no guarantee of continued maintenance**, updates, or bug fixes.
> - Use of this software is **entirely at your own risk**.

---

## License

```
MIT License

Copyright (c) 2026 Surrplexie

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
