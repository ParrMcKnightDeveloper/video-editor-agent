# Media in and out of a cloud session (SharePoint / OneDrive)

A Claude Code on the web session runs in a fresh container. It cannot see anyone's hard
drive, and the container is reclaimed when the session ends. So for this pack, in cloud
mode, **footage arrives as a link and renders leave as a link.** The team's media home is
SharePoint / OneDrive; the review page (here.now canvas) stays the primary way a reviewer
watches a cut.

The bridge is `scripts/fetch_media.py` (python3, stdlib only). `python3 scripts/fetch_media.py -h`
has every flag.

## Intake — footage from a sharing link

1. Ask for (or find with the Microsoft 365 connector's `sharepoint_search`) the **sharing
   link** of the source file. A link to the file, not the folder.
2. Fetch it into the projects directory, which in a cloud session is this pack's `outputs/`:

   ```bash
   python3 .claude/skills/video-edit-pipeline/scripts/fetch_media.py fetch "<share link>" \
     --dest outputs/<project-slug> --name source.mp4
   ```

   The script picks the route from the link: SharePoint / OneDrive for Business links get
   `download=1`; OneDrive personal links go through the public shares API; a direct https
   URL downloads as-is. It then **ffprobes the file** and prints the streams. A download
   that is not media is deleted and reported (an org-only link served a sign-in page).
3. **Org-only links** (the default sharing setting in most tenants) need a Microsoft Graph
   bearer token in `MS_GRAPH_TOKEN`; the script then uses the Graph shares API. Two ways
   to avoid needing one: ask the uploader to share with "Anyone with the link" (view), or
   have them drop the file where an already-shared folder link exists.
4. Probe before reasoning, as always. The JSON the script prints is the ffprobe result.

## Delivery — renders out

- **Primary: the review canvas.** `video-review-canvas` publishes the cut and the reply
  leads with the URL. Nothing changes here.
- **Also push the master to SharePoint** when the team wants the file in the library:

  ```bash
  python3 .claude/skills/video-edit-pipeline/scripts/fetch_media.py push outputs/<slug>/output-v2.mp4 \
    --drive-id <driveId> --folder-id <folderItemId> --link organization
  ```

  Needs `MS_GRAPH_TOKEN`. Uses a Graph **upload session** in 10 MiB chunks, so large
  masters work (the connector's own upload tool caps at 1 MB, which rules it out for
  video). `--conflict rename` is the default: delivered files are never overwritten. The
  `driveId` and folder `itemId` come from the connector (`sharepoint_folder_search`, or a
  `file:///<driveId>/<itemId>` resource URI). The command prints the item's `webUrl` and,
  with `--link`, a view-only sharing link to paste next to the canvas URL.

- **Small text artefacts** (spec JSON, EDL, notes, QA report, MASTER_CONTEXT) go through the
  connector directly: `sharepoint_upload_file` (≤ 1 MB) and `read_resource`.

## Where the token comes from

`MS_GRAPH_TOKEN` is a delegated Microsoft Graph access token with `Files.ReadWrite` (own
OneDrive) or `Sites.ReadWrite.All` (team libraries). For a person: sign in at Graph Explorer
(developer.microsoft.com/graph/graph-explorer), consent to those scopes, copy the access
token. It expires in about an hour, so set it as a session secret when a push is planned,
not permanently. For a team, an app registration with client credentials is the durable
route; that is an admin task, out of this pack's scope.

## Hosts to allowlist in the environment

`*.sharepoint.com` (and `*-my.sharepoint.com`), `graph.microsoft.com`, `1drv.ms`,
`api.onedrive.com`, plus wherever the tenant's CDN redirects downloads
(`*.sharepointonline.com`).

## Projects directory in cloud mode

`outputs/<slug>/` inside the container. It is gitignored and gone when the session ends,
which is fine: the source lives in SharePoint, the delivered cut lives on the canvas and
(optionally) in SharePoint, and every version is a new file in both places. Do not try to
keep working files across sessions in the container — re-fetch.
