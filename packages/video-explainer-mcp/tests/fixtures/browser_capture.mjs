import assert from 'node:assert/strict';
import childProcess, * as exported from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {readFileSync} from 'node:fs';
import {Script, createContext} from 'node:vm';

console.error(`browser capture: fixture entered (${process.version}, ${process.platform}, ${process.arch})`);
const source = readFileSync(process.argv[2], 'utf8');
const body = source.slice(source.indexOf('async function openOwnedBrowser('), source.indexOf('async function closeOwnedBrowser('));
assert(body.startsWith('async function openOwnedBrowser('));
const original = childProcess.spawn;
const events = [];
const inert = () => {events.push('spawn'); return {pid: 9001};};
childProcess.spawn = inert;
assert.notEqual(exported.spawn, inert);
syncBuiltinESMExports();
console.error('browser capture: creating VM context');
const context = createContext({childProcess, syncBuiltinESMExports,
  ownedBrowser: undefined, chromiumOptions: {disableWebSecurity: false, ignoreCertificateErrors: false}, custody: (state) => events.push(state),
  requireValue: (condition, message) => {if (!condition) throw new Error(message);}});
console.error('browser capture: compiling extracted helper');
const open = new Script(body + ';openOwnedBrowser').runInContext(context);
const spec = {browser: {path: '/owned/frozen/browser'}};
const spawn = () => exported.spawn(spec.browser.path, [], {detached: true});
const restored = () => {assert.equal(childProcess.spawn, inert); assert.equal(exported.spawn, inert);};
try {
  console.error('browser capture: control 1/4 successful capture');
  const browser = await open(async () => {spawn(); return {result: 'browser'};}, spec, 'token');
  assert.equal(browser.result, 'browser');
  assert.deepEqual(events, ['launching', 'spawn', 'registered']);
  restored(); events.length = 0;
  console.error('browser capture: control 2/4 rejection before launch');
  await assert.rejects(open(async () => {throw new Error('before launch');}, spec, 'token'), /before launch/);
  restored(); assert.deepEqual(events, []);
  console.error('browser capture: control 3/4 rejection after launch');
  await assert.rejects(open(async () => {spawn(); throw new Error('after launch');}, spec, 'token'), /after launch/);
  restored(); assert.deepEqual(events, ['launching', 'spawn', 'registered']);
  events.length = 0;
  console.error('browser capture: control 4/4 missing capture');
  await assert.rejects(open(async () => ({}), spec, 'token'), /Frozen browser spawn was not captured/);
  restored(); assert.deepEqual(events, []);
  console.log(JSON.stringify({controls: 4, native_child_spawns: 0, binding_capture_restore: 'PASS'}));
} finally {
  console.error('browser capture: final binding restoration');
  childProcess.spawn = original;
  syncBuiltinESMExports();
  assert.equal(exported.spawn, original);
}
