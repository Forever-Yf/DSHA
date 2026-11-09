#!/usr/bin/env python3
"""One-shot, fail-closed source migration from DSHA 0.2.1 to DSH 0.2.2-rc.1.

The input is an npm-ci installation, not user data. Generated recipes and the lock
are committed as normal source files by the build workflow before publication.
The original recovery runtime/recipes and the original Android data remain separate.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / 'app/src/main/assets'
INSTALL = Path(sys.argv[1]).resolve()
N = INSTALL / 'node_modules'
VERSION = '0.2.2-rc.1'

def read(name):
    return json.loads((A / name).read_text(encoding='utf-8'))

def save(name, value):
    (A / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def edit(path, old, new):
    path = ROOT / path
    text = path.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise ValueError('PORT_SOURCE_ANCHOR: ' + str(path) + ': ' + repr(old[:100]))
    path.write_text(text.replace(old, new), encoding='utf-8')

def patch(before, after, **kw):
    return dict(before=before, after=after, **kw)

def append_asset(path, field, name):
    file = ROOT / path
    data = json.loads(file.read_text())
    if name not in data[field]:
        data[field].append(name)
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

if json.loads((N / '@deepseek-ai/dsh/package.json').read_text())['version'] != VERSION:
    raise SystemExit('PORT_INPUT_VERSION')
current = json.loads((ROOT / 'tools/dsh-runtime/package.json').read_text())['version']
if current == VERSION:
    print('Production source is already 0.2.2; leaving existing reviewed recipes unchanged.')
    raise SystemExit(0)
if current != '0.2.1-rc.2':
    raise SystemExit('PORT_BASE_VERSION')

# Freeze the rescue capsule recipes independently before changing the main runtime.
(A / 'recovery-recipes').mkdir(exist_ok=True)
for name in ('pdf-compat-patch.json', 'language-patch.json'):
    shutil.copyfile(A / name, A / 'recovery-recipes' / name)
for name in ('package.json', 'package-lock.json'):
    shutil.copyfile(INSTALL / name, ROOT / 'tools/dsh-runtime' / name)

# The tool runtime now separates the service from its execution pipeline.
p = read('guard-tools-patch.json')
p['patches'] = [
    patch('import { Service } from "@deepseek-ai/cordis";', 'import { attachPolicy } from "dsha-destructive-policy"; // DSHA_REQUIRED_POLICY_V1\nimport { Service } from "@deepseek-ai/cordis";'),
    patch('\t\tsuper(ctx, "tools");', '\t\tsuper(ctx, "tools");\n\t\tattachPolicy(this, ctx);')]
save('guard-tools-patch.json', p)
before = '\t\t\tconst tool = this.resolveExecution(exec.name, exec.agent, exec.parent !== void 0, exec.toolSet);\n\t\t\tif (!tool) throw new ToolNotFoundError(exec.name);\n\t\t\tstate.bodyInvoked = true;'
p = dict(version=1, dshVersion=VERSION, module='@deepseek-ai/dsh-tools/lib/pipeline.js', sourceSha256='', patches=[
    patch('import { scopeTarget } from "@deepseek-ai/dsh-scope";', 'import { captureExecution, prepareOperation, verifyGlobalConsent, verifyDispatch } from "dsha-destructive-policy"; // DSHA_REQUIRED_PIPELINE_POLICY_V1\nimport { scopeTarget } from "@deepseek-ai/dsh-scope";'),
    patch('\t\t\tthis.deferredContexts.set(execution, deferredContexts);', '\t\t\tObject.defineProperties(execution, Object.fromEntries(["name", "arguments", "token", "callId", "rootCallId", "agent", "parent", "toolSet"].map(key => [key, { value: execution[key], writable: false, configurable: false, enumerable: true }])));\n\t\t\tcaptureExecution(this.tools, execution, visible);\n\t\t\tthis.deferredContexts.set(execution, deferredContexts);'),
    patch('\t\t\tconst denialReason = decision.kind === "allow" ? this.tools.checkGuards(exec) : decision.reason;', '\t\t\tif (decision.kind === "allow") await prepareOperation(this.tools, exec);\n\t\t\tconst denialReason = decision.kind === "allow" ? this.tools.checkGuards(exec) : decision.reason;'),
    patch(before, '\t\t\tawait verifyGlobalConsent(exec);\n' + before.replace('\t\t\tstate.bodyInvoked = true;', '\t\t\tverifyDispatch(this.tools, exec, tool);\n\t\t\tstate.bodyInvoked = true;'))])
save('guard-tools-pipeline-patch.json', p)
reg = read('runtime-patches.json')
index = next(i for i, row in enumerate(reg['active']) if row['asset'] == 'guard-tools-patch.json')
reg['active'].insert(index + 1, dict(asset='guard-tools-pipeline-patch.json'))
save('runtime-patches.json', reg)
append_asset('app/src/main/assets/managed-runtime-inputs.json', 'assetFiles', 'guard-tools-pipeline-patch.json')
append_asset('tools/asset-deployment.json', 'packagedFiles', 'guard-tools-pipeline-patch.json')

# A malformed tool batch becomes diagnostic text, not partially replayable calls.
p = read('tool-dispatch-validation-patch.json')
message = 'DSHA_INVALID_TOOL_CALL: missing name/id; this step was not dispatched. No automatic replay.'
helper = '// DSHA_TOOL_DISPATCH_IDENTITY_RC22_V1: validate the whole batch before executor side effects.\nfunction assertDshaToolCallBatch(toolCalls) {\n\tif (toolCalls.some(block => !(typeof block.id === "string" && block.id.trim() !== "" && typeof block.name === "string" && block.name.trim() !== ""))) throw new LlmError("' + message + '", "INVALID_RESPONSE");\n}\n'
before = '\t\t\t\tconst message = createAssistantMessage({\n\t\t\t\t\tcontent: live.blocks(),'
after = '''\t\t\t\t// DSHA_TOOL_FINISH_IDENTITY_RC22_V1: malformed batches are diagnostic text, never replayable calls.
\t\t\t\tconst assembledBlocks = live.blocks();
\t\t\t\tconst invalidIdentity = assembledBlocks.some(block => block.type === "tool-call" && !(typeof block.id === "string" && block.id.trim() !== "" && typeof block.name === "string" && block.name.trim() !== ""));
\t\t\t\tconst message = createAssistantMessage({
\t\t\t\t\tcontent: assembledBlocks.map(block => invalidIdentity && block.type === "tool-call" ? { type: "text", text: "[DSHA_INVALID_TOOL_CALL] Missing tool name/id in this batch. No tool in this step was executed; no automatic replay." } : block),'''
p['patches'] = [patch('//#region lib/types/inbox.js', helper + '//#region lib/types/inbox.js'), patch(before, after), p['patches'][2],
    patch('\t\t\t\tif (finish.kind === "max-tokens") return { kind: "max-tokens" };', '\t\t\t\tif (invalidIdentity) throw new LlmError("' + message + '", "INVALID_RESPONSE");\n\t\t\t\tif (finish.kind === "max-tokens") return { kind: "max-tokens" };'),
    patch('\t\t\t\t\tconst result = await this.loopCtx.tools.execute({', '\t\t\t\t\tassertDshaToolCallBatch(toolCalls);\n\t\t\t\t\tconst result = await this.loopCtx.tools.execute({')]
save('tool-dispatch-validation-patch.json', p)

# Upstream fixed resolver ownership using a plain object; preserve its new upload staging API.
p = read('file-upload-resolver-lifecycle-patch.json')
src = (N / p['module']).read_text()
anchor = '\t\tagentResolution = { resolver: void 0 };'
if anchor not in src:
    anchor = '\tagentResolution = { resolver: void 0 };'
p['reason'] = 'Upstream 0.2.2 implements the stable plain-object resolver holder; retain duplicate registration and stale-disposer fences.'
p['patches'] = [patch(anchor, '\t\t// DSHA_FILE_UPLOAD_RESOLVER_LIFETIME_V1: upstream stable holder preserves exact registration identity.\n' + anchor)]
save('file-upload-resolver-lifecycle-patch.json', p)

p = read('composer-enter-patch.json')
p['patches'][0]['before'] = '\t\t\tconst interruptible = running && (continuable || sending && subagent === null);'
p['patches'][5]['before'] = '\t\t\t\tif (locked || editor === null) return;\n\t\t\t\tif ((0, _deepseek_ai_dsh_client_ui_primitives.isMobileDevice)()) return;\n\t\t\t\tfocusDraftEditor(editor, revealSelection);'
save('composer-enter-patch.json', p)
p = read('sidebar-layout-recovery-patch.json')
src = (N / p['module']).read_text()
new = re.search(r'\t\tfunction RightbarSeat\(\{[^\n]+', src).group()
p['patches'][2]['before'] = new
p['patches'][2]['after'] = p['patches'][2]['after'].split('\t\tfunction DshaRightbarSeatBody(')[0] + new.replace('function RightbarSeat', 'function DshaRightbarSeatBody')
save('sidebar-layout-recovery-patch.json', p)
p = read('session-interaction-patch.json')
for key in ('before', 'after'):
    p['patches'][0][key] = p['patches'][0][key].replace('onUnarchive, t', 'onUnarchive, useSessionAccess, t')
p['patches'][3]['before'] = '\t\t\t\t"aria-description": result.archived ? t("toast.archivedNotOpenable") : void 0,\n' + p['patches'][3]['before']
save('session-interaction-patch.json', p)
p = read('plugin-manager-pending-patch.json')
helper = p['patches'][3]['after'].split('\t\tfunction EnableSwitch')[0]
anchor = '\t\tfunction EnableSwitch({ pkg, title, t, busy, onSetEnabled }) {'
p['patches'][3] = patch(anchor, helper + anchor)
save('plugin-manager-pending-patch.json', p)
p = read('config-editor-lock-order-patch.json')
for row in p['patches']:
    for key in ('before', 'after'):
        row[key] = re.sub(r'(\t+)const resolved = fiber.ctx.waterfall\(fiber, "internal/config", next, \(\) => next\);\n\t+resolveConfig\(fiber.runtime, resolved\);', r'\1fiber.resolveConfig(next);', row[key])
save('config-editor-lock-order-patch.json', p)
p = read('plugin-inventory-entries-patch.json')
helper = p['patches'][0]['after'].split('/** Read current Loader')[0]
anchor = 'async function readPluginInventory(ctx) {'
p['patches'][0] = patch(anchor, helper + anchor)
save('plugin-inventory-entries-patch.json', p)
p = read('retired-market-optional-patch.json')
p['module'] = '@deepseek-ai/dsh-official-bundles/lib/index.js'
before = '\t"@deepseek-ai/dsh-experimental-liveshare",\n\t"@deepseek-ai/dsh-experimental-plugin-market-bundle",\n\t"@deepseek-ai/dsh-experimental-tool-worktree",'
p['patches'] = [patch(before, before.replace('\t"@deepseek-ai/dsh-experimental-plugin-market-bundle",', '\t// DSHA_RETIRED_MARKET_OPTIONAL_V1: managed Android installer owns catalog changes.'))]
save('retired-market-optional-patch.json', p)
for row in reg['active']:
    if row['asset'] == 'retired-market-optional-patch.json':
        row.pop('module', None)
save('runtime-patches.json', reg)

# The new resource API already hashes file bytes for ETags; keep that implementation.
p = read('frontend-static-cache-patch.json')
helper = '''// DSHA_STATIC_CACHE_V3: weak HTTP validators match lists and wildcard values.
function dshaRevalidated(value, etag) {
\tif (value === null) return false;
\tconst normalized = etag.replace(/^W\\//, "");
\treturn value.split(",").some(part => {
\t\tconst tag = part.trim();
\t\treturn tag === "*" || tag.replace(/^W\\//, "") === normalized;
\t});
}
'''
anchor = 'async function serveStatic(request, distRoot, distIndex, authorizeIndex, renderIndex) {'
p['patches'] = [patch(anchor, helper + anchor), patch('headers = { "content-type": HTML_MIME };', 'headers = { "content-type": HTML_MIME, "cache-control": "no-store", "vary": "Cookie" };'), patch('request.headers.get("if-none-match") === cache.etag', 'dshaRevalidated(request.headers.get("if-none-match"), cache.etag)')]
save('frontend-static-cache-patch.json', p)

# Bind the reviewed Tooltip closure to the actual new compiled asset.
p = read('tooltip-interaction-patch.json')
p['module'] = '@deepseek-ai/dsh-web-frontend/dist/assets/index-BgUyXZcc.js'
before = 'le=k.useCallback(()=>{ae(),X.current={hover:!1,focus:!1},he()},[ae,he]);vy'
after = before[:-2] + '/* DSHA_TOOLTIP_DISMISS_RC2_V1 */k.useEffect(()=>{if(!ee)return;const dshaClose=E=>{if(E?.type==="scroll"&&E.target!==window&&L.current?.contains(E.target))return;le()},dshaPointer=()=>{if(!g)le()},dshaKey=E=>{if(E.key==="Escape"&&!g)le()},dshaHidden=()=>{if(document.hidden)le()};document.addEventListener("scroll",dshaClose,!0),document.addEventListener("pointerdown",dshaPointer,!0),document.addEventListener("keydown",dshaKey),document.addEventListener("visibilitychange",dshaHidden),window.addEventListener("blur",dshaClose);return()=>{document.removeEventListener("scroll",dshaClose,!0),document.removeEventListener("pointerdown",dshaPointer,!0),document.removeEventListener("keydown",dshaKey),document.removeEventListener("visibilitychange",dshaHidden),window.removeEventListener("blur",dshaClose)}},[le,ee,g]);vy'
p['patches'] = [patch(before, after)]
save('tooltip-interaction-patch.json', p)
p = read('tooltip-entry-patch.json')
p['patches'] = [patch('src="./assets/index-BgUyXZcc.js"', 'src="./assets/index-BgUyXZcc.js?dsha-tooltip=0.2.2-rc1-1"')]
save('tooltip-entry-patch.json', p)

# New listBundles delegates to a separate reader; retain awaited signed package proofs.
p = read('plugin-manager-policy-patch.json')
p['patches'] += [patch('return Promise.resolve(this.readBundles().map((bundle) => ({', 'return (await this.readBundles(dshaOnlyName)).map((bundle) => ({'), patch('updatable: typeof updateRefusal(bundle, bundle.name) !== "string"\n\t\t\t})));', 'updatable: typeof updateRefusal(bundle, bundle.name) !== "string"\n\t\t\t}));'), patch('\t\treadBundles() {', '\t\tasync readBundles(dshaOnlyName) {')]
save('plugin-manager-policy-patch.json', p)

# Refresh version/integrity evidence from actual pinned npm bytes, never guessed hashes.
lock = json.loads((INSTALL / 'package-lock.json').read_text())
reg = read('runtime-patches.json')
modules = {row['asset']: row.get('module') for row in reg['active']}
recipes = set(modules) | {name for name in reg['specialized'] if name.endswith('.json')} | {'lexical-claim-patch.json', 'conversation-materialized-patch.json'}
for name in recipes:
    p = read(name)
    p['dshVersion'] = VERSION
    if p.get('packageVersion') == '0.2.1-rc.2':
        p['packageVersion'] = VERSION
    module = modules.get(name) or p.get('module')
    if module and (N / module).is_file():
        digest = hashlib.sha256((N / module).read_bytes()).hexdigest()
        for key in ('sourceSha256', 'canonicalSourceSha256'):
            if key in p:
                p[key] = digest
        if 'packageIntegrity' in p:
            package = '/'.join(module.split('/')[:2])
            p['packageIntegrity'] = lock['packages']['node_modules/' + package]['integrity']
    save(name, p)
reg['dshVersion'] = VERSION
save('runtime-patches.json', reg)

# Rebase bounded workers over the actual upstream platform/listing fields.
sys.path.insert(0, str(ROOT / 'tools'))
from runtime_stable_patches import load_chains, apply
chains, _ = load_chains(A, VERSION)
module = '@deepseek-ai/dsh-plugin-manager/lib/index.js'
data = (N / module).read_bytes()
for row in chains[module]:
    if row[0] == 'plugin-bundle-proof-workers-patch.json':
        break
    data = apply(data, [row])
text = data.decode()
start = text.index('\t\t\tconst bundles = [];\n\t\t\tconst dshaProofSession')
end = text.index('\n\t\t\treturn bundles;', start) + len('\n\t\t\treturn bundles;')
before = text[start:end]
loop = '\t\t\tfor (const name of names) {'
head, body = before.split(loop, 1)
body = body.rsplit('\n\t\t\t}\n\t\t\treturn bundles;', 1)[0]
if body.count('continue;') != 3:
    raise ValueError('PORT_WORKER_CONTROL_FLOW')
body = body.replace('continue;', 'return bundles;')
p = read('plugin-bundle-proof-workers-patch.json')
old = p['patches'][0]['after']
closing = old[old.index('\n\t\t\t\t\treturn bundles;\n\t\t\t\t};'):]
after = '\t\t\t// DSHA_PLUGIN_BUNDLE_READ_WORKERS_V2: bounded workers retain full signed proof checks.\n\t\t\tconst dshaRows = [], dshaJobs = new Set();\n\t\t\tlet dshaFailure;\n' + head + loop + '\n\t\t\t\tconst index = dshaRows.length;\n\t\t\t\tdshaRows.push([]);\n\t\t\t\tconst dshaReadBundle = async () => {\n\t\t\t\t\tconst bundles = [];' + body + closing
p['patches'] = [patch(before, after)]
save('plugin-bundle-proof-workers-patch.json', p)

# Preserve the new empty-table and atomic multi-delete semantics in the proot hint adapter.
f = 'tools/build-dsh-runtime.py'
edit(f, '\\t\\t\\tif (records !== void 0) return loadTableRecords(records, versions, join(dir, entry.name));', '\\t\\t\\tif (records !== void 0) {\n\\t\\t\\t\\tawait loadTableRecords(records, versions, join(dir, entry.name));\n\\t\\t\\t\\treturn true;\n\\t\\t\\t}')
edit(f, '\\tconst hasDocuments = files.some((file) => file.name.endsWith(".json"));\n', '')
edit(f, "table_replacement = '''\\tlet files;", "table_replacement = '''\\tlet files;\n\\tlet tablePresent = true;")
edit(f, '\\t\\tfiles = [];\n\\t}\n\\tconst listed', '\\t\\ttablePresent = false;\n\\t\\tfiles = [];\n\\t}\n\\tconst listed')
edit(f, '\\tconst hasDocuments = candidates.some((file) => listed.has(file) && file.endsWith(".json"));\n', '')
edit(f, '\\treturn hasDocuments;\n}\n/** Read one record document;', '}\n/** Read one record document;')
edit(f, '\\treturn hasDocuments || hintedDocument;', '\\t// A materialized empty table suppresses legacy bootstrap in 0.2.2.\n\\treturn tablePresent || hintedDocument;')
edit(f, "('''\\t\\tawait this.tracked(rm(join(this.tableDir(table), `${key}.json`), { force: true }));''',\n             '''\\t\\tconst dir = this.tableDir(table);\n\\t\\tawait this.tracked(rm(join(dir, `${key}.json`), { force: true }));\n\\t\\tthis.dshaRecordHints.forget(dir, key);''')", "('''\\t\\tawait this.tracked(this.removeDocuments(dir, unique));''',\n             '''\\t\\tawait this.tracked(this.removeDocuments(dir, unique));\n\\t\\tfor (const key of unique) this.dshaRecordHints.forget(dir, key);''')")

# The rescue capsule consumes its own recipes, not the new main-runtime version labels.
for file in ('tools/recovery_runtime_overlay.py', 'app/src/main/java/com/deepseekharness/app/recovery/RecoveryRuntime.java', 'tools/test-recovery-browser-overlay.mjs'):
    path = ROOT / file
    text = path.read_text()
    for name in ('pdf-compat-patch.json', 'language-patch.json'):
        text = text.replace("'" + name + "'", "'recovery-recipes/" + name + "'").replace('"' + name + '"', '"recovery-recipes/' + name + '"')
    path.write_text(text)
for name in ('pdf-compat-patch.json', 'language-patch.json'):
    append_asset('tools/asset-deployment.json', 'packagedFiles', 'recovery-recipes/' + name)
edit('app/build.gradle', 'inputs.file(rootProject.file("tools/recovery_runtime_overlay.py"))', 'inputs.file(rootProject.file("tools/recovery_runtime_overlay.py"))\n    inputs.files(fileTree("src/main/assets/recovery-recipes"))')
edit('app/build.gradle', "ext.dshaApkNameVersion = '0.2.1-rc.2'", "ext.dshaApkNameVersion = '0.2.2-rc.1-fork.1'")
edit('app/build.gradle', 'applicationId "dsh.android.client"', 'applicationId "io.github.foreveryf.dsha"')
edit('app/build.gradle', 'versionCode 190', 'versionCode 191')
edit('app/build.gradle', 'versionName "0.2.1-rc.2-20261022.2100-dsh0.2.1-rc.2"', 'versionName "0.2.2-rc.1-fork.1-dsh0.2.2-rc.1"')
edit('app/src/main/java/com/deepseekharness/app/util/Constants.java', 'DSH_VERSION = "0.2.1-rc.2"', 'DSH_VERSION = "0.2.2-rc.1"')
edit('app/src/main/java/com/deepseekharness/app/util/Constants.java', 'https://github.com/DSH-APP/DSHA', 'https://github.com/Forever-Yf/DSHA')
edit('app/src/main/java/com/deepseekharness/app/util/AppIdentity.java', 'return "dsh.android.client";', 'return "io.github.foreveryf.dsha";')
edit('app/src/main/java/com/deepseekharness/app/ui/BrowserOriginRestore.java', 'dsh.android.client.ORIGIN_RESTORE_QUIESCE', 'io.github.foreveryf.dsha.ORIGIN_RESTORE_QUIESCE')
print('Ported source and exact npm lock; runtime generation, execution and Android acceptance remain mandatory.')
