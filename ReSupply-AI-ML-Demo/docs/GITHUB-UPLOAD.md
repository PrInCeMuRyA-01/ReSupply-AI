# GitHub upload: English + Hinglish

Use the clean extracted source from this kit. Your working local app can keep running separately.

**Hinglish:** Working app ko waise hi rakho. Is clean ZIP ko alag folder mein extract karke wahi source GitHub par upload karo.

## 1. Choose the correct folder

The repository root should directly contain:

- `README.md`
- `START-HERE.md`
- `LICENSE`
- `.gitignore`
- `backend/`
- `docs/`
- `tests/`

Open **this folder** in VS Code. Its terminal should show the project root, not `backend`. Do not upload only the ZIP or wrap the whole repository in another project folder.

**Hinglish:** Jis folder mein README aur backend dono hain, wahi root hai. Git commands backend ke andar se mat chalao. GitHub par ZIP file ki jagah extracted source upload hogi.

This clean package contains no `.env`, virtual environment or shop database. Keep it that way. `backend/.env.example` contains placeholders and should be included. The strengthened `.gitignore` excludes local secrets, databases and recordings.

**Hinglish:** Apni working app wali `.env`, `.venv`, `resupply.db` ya `resupply-demo.db` is folder mein copy mat karo. `.env.example` upload karna hai kyunki usmein placeholder hai.

## 2. Create a public repository

At [GitHub](https://github.com/), sign in and choose **New repository**:

| Field | Value / action |
| --- | --- |
| Name | `ReSupply-AI` |
| Description | `AI-guided restocking for small shops with reviewed budgets and PayPal Sandbox payments.` |
| Visibility | **Public** |
| Initialize README | Leave unchecked; this package already has one. |
| Add .gitignore / license | Leave unset; the supplied files will be uploaded. |

Create the repository and copy its HTTPS URL from **Quick setup**.

**Hinglish:** Public repo banao. Website se naya README/license/gitignore add mat karo; package mein ye sab ready hain. Create ke baad apna actual HTTPS repo URL copy karna.

## 3. Recommended route: Git in VS Code PowerShell

Check Git:

```powershell
git --version
```

If Git is unavailable, use the browser route below or install [Git for Windows](https://git-scm.com/download/win) and reopen VS Code.

In the **clean project root**:

```powershell
git init -b main
git config user.name "Prince Maurya"
git config user.email "YOUR_GITHUB_VERIFIED_EMAIL"
git add .
git status --short
git ls-files
```

Replace `YOUR_GITHUB_VERIFIED_EMAIL` before committing. It can be your GitHub-provided no-reply address from account email settings.

Review the staged filenames. Source, docs, tests, LICENSE and `.env.example` should appear. Local `.env`, `.venv` and databases should not.

**Hinglish:** Email wali placeholder ko apni GitHub email/no-reply email se replace karo. Commit se pehle files ki list dekho. Real secret ya database list mein nahi hona chahiye.

Then:

```powershell
git commit -m "Build ReSupply AI with reviewed purchasing and PayPal Sandbox"
git remote add origin "PASTE_YOUR_ACTUAL_HTTPS_REPOSITORY_URL"
git remote -v
git push -u origin main
```

Replace the URL placeholder with your copied repository URL, for example the actual `https://github.com/your-account/ReSupply-AI.git` for your account.

If Git Credential Manager opens a browser, complete the normal GitHub sign-in. Do not paste a PayPal secret into GitHub authentication. GitHub account passwords are not Git HTTPS access tokens.

**Hinglish:** URL mein apna actual repo link lagao. Browser login aaye to GitHub account se login karo. PayPal credentials ka yahan koi use nahi hai.

## 4. Browser route if Git is not installed

1. Open the new repository's **uploading an existing file** link. Once the repo has files, use **Add file → Upload files**.
2. Upload `backend`, `docs`, `tests` and the root files listed above. Enable hidden-file visibility so `.gitignore` is included.
3. Confirm files appear directly at the repository root; remove an accidental extra outer folder before committing.
4. Commit the files to `main` with a short message.

**Hinglish:** Upload files mein folders aur root files select karo. Upar ek extra ReSupply-AI folder ke andar sab mat daalna. `.gitignore` hidden ho sakti hai, usko bhi include karo.

Browser upload does not use your local `.gitignore` to filter selected files. Use the clean package, not your running backend folder.

**Hinglish:** Website par drag/drop karne se ignore rules apne aap filter nahi karte. Isliye clean source folder hi upload karo.

## 5. Make the repository presentable

- Open the public URL while signed out. README should render on the repository home page.
- Confirm the **MIT license** is detected.
- In **About**, use the description above. Suggested topics: `python`, `fastapi`, `machine-learning`, `inventory-management`, `paypal`, `hackathon`.
- Follow the README on a fresh copy to confirm setup instructions.
- After publishing the video, add its actual public URL under the README presentation section.
- Optional: capture real demo-shop screenshots of Dashboard, Forecast, Planner and the receipt, save them in `docs/screenshots/`, and add relative image links after those images exist. Exclude login fields, credentials and customer information.

**Hinglish:** Logout/incognito se repo kholo. README aur MIT badge dikhna chahiye. Video ready hone ke baad actual YouTube link README mein add karo. Screenshots chahiye to apni actual demo app se lo.

For later documentation changes:

```powershell
git add README.md docs
git commit -m "Add public demo video and presentation details"
git push
```

## Common issues

| Issue | English | Hinglish |
| --- | --- | --- |
| `git` not recognized | Install Git and reopen VS Code, or use browser upload. | Git install karke VS Code dubara kholo, ya web upload karo. |
| `remote origin already exists` | Inspect `git remote -v`. If it points to the wrong repo, set the correct URL with `git remote set-url origin "ACTUAL_URL"`. | Pehle existing URL dekho; galat ho to correct URL set karo. |
| `src refspec main does not match` | Confirm a commit exists and run `git branch -M main`, then push. | Commit hona chahiye; branch ka naam main karke push karo. |
| Push rejected after repo initialization | Clone that repo into a new folder, copy the clean source into it, then add/commit/push. Do not force-push over work you have not reviewed. | Naye folder mein repo clone karo, clean source copy karke normal commit/push karo. |
| README shows only a ZIP | Upload the extracted source files at the root. | ZIP ke andar ki files upload karo. |

Official references: [adding local code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github?platform=windows) · [browser uploads](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).
