const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const songs = JSON.parse(fs.readFileSync('songs.json', 'utf8'));
const source = fs.readFileSync('app.js', 'utf8');
const match = source.match(/function dayGroups\(found\)\{[\s\S]*?\n\}\nconst dayOffsetLabel/);
assert.ok(match, 'Could not find the This Day grouping function');
const dayGroups = vm.runInNewContext(`(${match[0].slice(0, -'\nconst dayOffsetLabel'.length)})`);

let dated = 0;
const datesById = new Map();
for (const song of songs) {
  for (const kind of ['first', 'last', 'best']) {
    const performance = song[kind];
    if (!performance?.date) {
      assert.equal(performance?.showId, undefined, `${song.name} ${kind} has an ID without a date`);
      continue;
    }
    dated++;
    assert.match(performance.showId || '', /^gd-\d{4}-\d{2}-\d{2}(?:-[a-z0-9-]+)?$/, `${song.name} ${kind}`);
    const knownDate = datesById.get(performance.showId);
    assert.ok(!knownDate || knownDate === performance.date, `${performance.showId} spans different dates`);
    datesById.set(performance.showId, performance.date);
  }
}

const sameShow = dayGroups([
  {s: {name: 'A'}, k: 'best', ki: 2, off: 0, p: {date: '1972-09-27', showId: 'gd-1972-09-27', venue: 'Stanley Theater - Jersey City, NJ'}},
  {s: {name: 'B'}, k: 'first', ki: 0, off: 0, p: {date: '1972-09-27', showId: 'gd-1972-09-27', venue: 'Stanley Theatre - Jersey City, NJ'}},
  {s: {name: 'C'}, k: 'last', ki: 1, off: 0, p: {date: '1994-09-27', showId: 'gd-1994-09-27', venue: 'Boston Garden - Boston, MA'}},
]);
assert.equal(sameShow.length, 2, 'Different spellings of one show must group together');
assert.equal(sameShow[0].items.length, 2);
assert.equal(sameShow[1].items.length, 1);
console.log(`Validated ${dated} dated performances across ${datesById.size} concert IDs.`);
