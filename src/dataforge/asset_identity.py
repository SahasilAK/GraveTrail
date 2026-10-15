"""Conservative asset identities with explicitly supplied temporary job/session namespaces."""
import json
import posixpath

from dataforge.models import Diagnostic, canonical, stable_id


def source_job(source, config):
    job = config.get("default_job", "workspace")
    for prefix, override in sorted(config.get("job_by_folder", {}).items(), key=lambda item: len(item[0])):
        if source["relative_path"].startswith(prefix):
            job = override
    return job


def asset_job(asset):
    metadata = asset.get("metadata", {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return asset.get("job_id") or metadata.get("job_id")


def asset_label(asset):
    job = asset_job(asset)
    return asset["name"] + (f" [job: {job}]" if job and job != "workspace" else "")


def job_assets(assets, job):
    return [asset for asset in assets if not (asset["temporary"] or asset["kind"] == "unresolved")
            or (asset_job(asset) or "workspace") == job]


def unambiguous_job_assets(assets, job):
    grouped = {}
    for asset in job_assets(assets, job):
        grouped.setdefault(canonical(asset["name"]), []).append(asset)
    return {name: items[0] for name, items in grouped.items() if len(items) == 1}


class AssetResolver:
    def __init__(self, workspace, results, config):
        self.workspace, self.config = workspace, config
        self.norm = (lambda name: name.strip()) if config["case_sensitive"] else canonical
        refs = [(source_job(source, config), ref) for source, parsed in results
                for ref in [*parsed.assets, *(r for op in parsed.operations for r in [*op.sources, *op.targets])]]
        self.temporary = {(job, self.norm(ref.name)) for job, ref in refs
                          if ref.temporary or ref.name.startswith("#")}
        persistent_refs = [(source_job(source, config), ref) for source, parsed in results
                           for op in parsed.operations if op.method != "llm" for ref in op.targets
                           if not ref.temporary and not ref.name.startswith("#")]
        persistent_targets = {(job, self.norm(ref.name)) for job, ref in persistent_refs}
        self.conflicts = self.temporary & persistent_targets
        self.global_known, self.by_job = {}, {}
        for job, ref in refs:
            key = self.norm(ref.name)
            self.by_job.setdefault(job, {})[key] = ref
            if (job, key) not in self.temporary or ref.kind == "file":
                self.global_known[key] = ref
        # Explicit persistent writes remain global even when local temporary writes collide.
        self.global_known.update({self.norm(ref.name): ref for _, ref in persistent_refs})
        self.registry, self.aliases = {}, set()

    @staticmethod
    def _warn(parsed, text, name):
        if not any(item.message == text for item in parsed.diagnostics):
            parsed.diagnostics.append(Diagnostic(text, symbol=name))

    def visible_from(self, name, declaration_source, source):
        job = source_job(declaration_source, self.config)
        return (job, self.norm(name)) not in self.temporary or job == source_job(source, self.config)

    def known_names(self, source):
        job = source_job(source, self.config)
        return {ref.name for key, ref in {**self.global_known, **self.by_job.get(job, {})}.items()
                if (job, key) not in self.conflicts}

    def resolve(self, ref, metadata, parsed, role="reference"):
        job = source_job(metadata, self.config)
        known = {**self.global_known, **self.by_job.get(job, {})}
        name, changed, old = ref.name, False, None
        key = self.norm(name)
        if ref.kind == "file":
            path = name.removeprefix("file:")
            relative = "file:" + posixpath.normpath(posixpath.join(posixpath.dirname(metadata["relative_path"]), path))
            if key not in known and self.norm(relative) in known:
                key = self.norm(relative)
                name = known[key].name
        elif "." not in key and (job, key) not in self.temporary:
            candidates = [k for k, r in known.items() if r.kind != "file" and "." in k and k.rsplit(".", 1)[-1] == key]
            if len(candidates) == 1:
                old = key
                key, name = candidates[0], known[candidates[0]].name
                changed = True
            elif len(candidates) > 1:
                self._warn(parsed, f"Ambiguous table {name}; candidates: {', '.join(candidates)}", name)
        temporary = (job, key) in self.temporary
        kind, identity = ref.kind, key
        if role == "output":
            temporary = ref.temporary or ref.name.startswith("#")
        elif (job, key) in self.conflicts and not ref.temporary:
            self._warn(parsed, f"Temporary and persistent writes share {name} in job {job}; read identity unresolved", name)
            temporary, kind, identity, changed = False, "unresolved", "unresolved:" + key, True
        scoped = temporary or kind == "unresolved"
        needs_scope = scoped and (job != "workspace" or (temporary and (
            key in self.global_known or (job, key) in self.conflicts)))
        aid = (stable_id(self.workspace, identity, "job", job) if needs_scope
               else stable_id(self.workspace, identity))
        if old is not None:
            self.aliases.add((self.workspace, old, aid, "unique-qualified-match"))
        if aid not in self.registry:
            self.registry[aid] = [aid, self.workspace, name, key, kind, temporary,
                                  json.dumps({"job_id": job}) if scoped else "{}"]
        else:
            self.registry[aid][5] |= temporary
        return aid, changed
