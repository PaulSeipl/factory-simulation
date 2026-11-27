# Publishing the MES planner image

The MES runs the planner (this bridge with the thesis scheduler) as the compose service `planner`, from the image
`ghcr.io/fidentis-gmbh/mes-planner:<version>`. The MES repository only names the version; it never needs this
repository. How the MES side is set up: `docs/deployment/planner.md` in the MES repository.

## Once

1. **Docker Desktop** running.
2. **A token to push:** GitHub → Settings → Developer settings → Personal access tokens → *Tokens (classic)* →
   new token with the scope `write:packages` (it includes `read:packages`). If the FIDENTIS-GmbH organization uses
   single sign-on, click *Configure SSO* next to the token and authorize it for the organization.
3. **Log in** (the token is the password; Docker stores it, so this is needed once per machine):
   ```powershell
   docker login ghcr.io -u <your GitHub user name>
   ```
4. **The organization admin** allows members to create private packages (organization Settings → Member
   privileges → Package creation). Your first push creates the package `mes-planner` and makes you its admin; set
   its visibility to *private* (it is by default) and give the MES VM's read account access (package page →
   *Package settings* → *Manage access*).

## Every release

From the repository root, on a clean, committed state (the image is what is committed, not your working copy;
check with `git status`):

```powershell
$v = "v0.1.0"                                   # the new version, never reuse one
cd mes_bridge; uv run pytest -q; cd ..          # the bridge tests must pass
docker build -f mes_bridge/Dockerfile -t ghcr.io/fidentis-gmbh/mes-planner:$v `
    --label org.opencontainers.image.revision=$(git rev-parse HEAD) .
docker push ghcr.io/fidentis-gmbh/mes-planner:$v
git tag planner-$v; git push origin planner-$v  # which commit is in which image
```

Then in the MES repository set the new version (`PLANNER_TAG` in `docker-compose.yml`, or in the VM's `.env`).
The next `docker compose up` on the VM pulls it, because that version is not on the VM yet.

## Check an image before pushing

Against a running MES (the scheduler account must exist there):

```powershell
docker run --rm -e MES_SCHEDULER_PASSWORD=... --entrypoint python ghcr.io/fidentis-gmbh/mes-planner:$v `
    -m mes_bridge.once --url http://host.docker.internal:8080 --dry-run
```

It plans once from the MES's problem and checks the plan, without publishing.

## Notes

- Versions are fixed tags (`v0.1.0`, `v0.2.0`, …), never `latest`, so an update on the VM is a decision.
- The image holds no secret: the passwords and the events token come from the MES's `.env`.
- The image contains the thesis code (installed Python). Keep the package private.
- torch is not in the image: the RL planner is an optional extra of the thesis package (`uv sync --extra rl`).
