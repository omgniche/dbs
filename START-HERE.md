# DontBetSports: start here

Everything you need to get the site, the AI newsroom and the In Public page running.
Do Parts 1 to 4 once. After that, your only daily job is Part 5.

---

## What's in this folder

| File or folder | What it is | Do you edit it? |
|---|---|---|
| `posts/` | Every article, one text file each | Only for your own posts |
| `build.py` | Turns posts into the website | Settings at the top only |
| `static/` | Logo and design | No |
| `newsroom/run.py` | The AI newsroom | Settings at the top only |
| `newsroom/style.md` | Your writing voice and rules for the AI | Yes, anytime |
| `newsroom/sources.json` | The 128 official team and league pages it watches | Only to fix broken sources |
| `newsroom/readership.py` | Pulls your real reader numbers each day | No |
| `.github/workflows/` | The timers that run everything automatically | No |
| `netlify.toml` | Tells Netlify how to build the site | No |

To edit any file later: open it on github.com, tap the pencil icon, make the change, then tap **Commit changes**.

---

## Part 1. Put the site online (about 20 minutes)

1. **Make a GitHub account** at github.com.
2. **Create a repository.** Tap **New repository**, name it `dontbetsports`, choose **Public** (this keeps the automation free), and create it.
3. **Upload the files.** Unzip this folder on a computer. In your new repo, choose **Add file → Upload files**, then drag in everything inside the folder.
   Important: include the hidden `.github` folder. On a Mac, press Cmd + Shift + . in Finder to show hidden folders. On Windows, turn on View → Hidden items.
   Tap **Commit changes**.
4. **Connect Netlify.** At netlify.com, choose **Add new site → Import an existing project → GitHub**, pick `dontbetsports`, and deploy. The settings fill in automatically.
5. **Connect your domain.** In Netlify, open **Domain management** and add `dontbetsports.com`. Follow its steps to point your domain at Netlify.

Your site is now live. Every time a post is added, Netlify rebuilds it automatically.

---

## Part 2. Turn on the AI newsroom (about 15 minutes)

1. **Get an AI key.** At console.anthropic.com: create an account, add a payment method, and set a **monthly spending limit** (start at $30). Then create an API key and copy it. You only see it once.
2. **Give GitHub the key.** In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
   - Name: `ANTHROPIC_API_KEY`
   - Secret: paste the key
3. **Let the newsroom send you drafts.** In your repo: **Settings → Actions → General**, scroll to **Workflow permissions**, choose **Read and write permissions**, tick **Allow GitHub Actions to create and approve pull requests**, and save.
4. **First run.** Open the **Actions** tab, tap **Newsroom**, then **Run workflow**. This first run only memorizes the stories already on every team's page, so it won't write about old news.
5. **Check the log.** Tap the finished run and open **Run the newsroom**. Any source marked with `!` didn't load. For each one, open `newsroom/sources.json`, find that team, and either fix the URL with the team's current news page or delete those lines.

From here it runs by itself every 30 minutes.

---

## Part 3. Turn on the In Public page (about 15 minutes)

The page is already live at `dontbetsports.com/in-public/`. The promise counter and newsroom numbers fill in on their own. Reader numbers need analytics.

1. **Sign up for Plausible** at plausible.io and add the site `dontbetsports.com`.
2. **Add the tracking code.** Plausible shows you a short snippet that starts with `<script`. Copy it. On GitHub, open `build.py`, tap the pencil, find the line `ANALYTICS_SNIPPET = """"""`, and paste the snippet between the middle quotes so it looks like:
   `ANALYTICS_SNIPPET = """<script ...></script>"""`
   Commit the change.
3. **Set your partner email.** In the same file, change `CONTACT_EMAIL = "partners@dontbetsports.com"` to the address you want sponsors to use. Commit.
4. **Create a Plausible API key.** In Plausible: **Account settings → API keys → New API key**, choose the **Stats API**, and copy the key.
5. **Give GitHub the Plausible details.** In your repo: **Settings → Secrets and variables → Actions**, and add two secrets:
   - `PLAUSIBLE_API_KEY`: the key you just copied
   - `PLAUSIBLE_SITE`: `dontbetsports.com`
6. **Wait a day, then test.** Once Plausible has a day of visits, go to **Actions → In Public numbers → Run workflow**. After that it updates every morning by itself.

The page only ever shows real numbers from your analytics. Until there's data, it says so instead of showing anything made up.

---

## Part 4. Set up your phone (5 minutes)

1. Install the **GitHub** app and sign in.
2. Open your repo, tap **Watch → Custom**, and turn on **Pull requests**.
3. Allow notifications from the GitHub app.

---

## Part 5. Your daily routine

When a draft arrives, you get a notification like: *"Ravens' Lamar Jackson to have thumb surgery, heads to IR."*

1. **Open it.** The top shows the source link, the story type, and what the fact-checker removed.
2. **Preview it.** Scroll to Netlify's **Deploy Preview** link and tap it to see the post exactly as it will look.
3. **Decide.**
   - **Publish:** tap **Merge pull request**, then **Confirm**. It's live in about a minute.
   - **Reject:** tap **Close pull request**. It won't come back.
   - **Edit first:** open the pull request in your phone's browser on github.com, go to **Files changed**, tap the three dots on the file, choose **Edit file**, fix it, commit, then merge.

Up to 15 drafts a day, and usually fewer.

---

## Part 6. Writing your own posts

1. On GitHub, open the `posts` folder and open `_TEMPLATE-news-post.md`. Copy its text.
2. Tap **Add file → Create new file**. Name it with lowercase words and dashes, ending in `.md`, like `celtics-trade-deadline-takes.md`. That name becomes the web address.
3. Paste the template and fill in the top section:
   - `title:` the headline
   - `description:` one or two sentences, shown in Google results
   - `date:` like 2026-11-06
   - `author:` your name
   - `category:` News or Takes
   - `league:` NFL, NBA, MLB or NHL (optional)
   - `featured: true` puts it in the big spot on the homepage (optional)
4. Delete the `draft: true` line, write your post below the `---`, and commit. It goes live automatically.

---

## Settings you can change

**In `newsroom/run.py` (top of the file):**
- `MIN_SCORE`: how important a story must be to get drafted (1–10). Raise to 9 for fewer drafts.
- `MAX_DRAFTS_PER_DAY`: your daily review limit.
- `KEEP_TYPES`: which kinds of stories count as news.

**In `newsroom/style.md`:** how the AI writes. Change the voice anytime.

**In `build.py` (top of the file):** site address, X handle, partner email and analytics snippet.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| No drafts are arriving | Actions tab → check the latest Newsroom run. A red X means it failed; open it to see why. |
| A source keeps failing | Fix or delete it in `newsroom/sources.json`. |
| "Resource not accessible by integration" error | Part 2, step 3 wasn't saved. |
| AI error mentioning credit or billing | Add funds or raise your limit at console.anthropic.com. |
| Merged a post but the site didn't change | Netlify → Deploys. Open the failed deploy and read the error. |
| In Public shows no reader numbers | Check both Plausible secrets, wait a day for data, then rerun the In Public workflow. |

For anything else, copy the error message and the file name it mentions and paste them to Claude.
