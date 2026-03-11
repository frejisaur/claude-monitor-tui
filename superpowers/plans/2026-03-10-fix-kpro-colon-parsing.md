# Fix .kpro Colon Parsing Truncation

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix profile_description (and all other fields) being truncated when the value contains colons.

**Architecture:** The `.kpro` file format uses `key:value` lines. The current parser uses `line.split(":")` which splits on every colon, then destructures `[key, value]` — discarding everything after the second colon. Fix by splitting only on the first colon. The colon-split bug affects 3 locations: backend parser (2 functions in `kl-parsers.js`), and frontend parser (1 function in `roast-sync.service.ts`). The backend also has a secondary bug where `\r`/`\v` replacement uses string `.replace()` instead of regex with `/g` flag, so only the first occurrence is replaced. The frontend already uses global regex correctly.

**Tech Stack:** Node.js, Jest, Angular/TypeScript, Playwright

---

## Chunk 1: Backend Parser Fix

### Task 1: Add test .kpro file with colons in description

**Files:**
- Create: `test_data/kaffelogic/roast-profiles/ColonTest.kpro`

- [ ] **Step 1: Create a test .kpro file with colons in the description**

The file needs a `profile_description` containing colons and multiple `\v` sequences to exercise both bugs.

```
profile_short_name:ColonTest
profile_designer:Test Author
profile_description:Step 1: Preheat to 200C.\vStep 2: Drop beans at 180C.\vStep 3: First crack at ~200C.\vNotes: Use 100g batch.
profile_schema_version:1.4
emulation_mode:0.0
recommended_level:3.2
expect_fc:0.0
expect_colrchange:0.0
preheat_power:550
preheat_nominal_temperature:240.0
reference_load_size:100
roast_end_by_time_ratio:100
roast_required_power:1200
roast_min_desired_rate_of_rise:0.0
roast_profile:	0.0	20.0	40.0
fan_profile:	0.0	50.0	100.0
roast_levels:	200.0	210.0	220.0
```

- [ ] **Step 2: Commit test fixture**

```bash
git add test_data/kaffelogic/roast-profiles/ColonTest.kpro
git commit -m "test: add .kpro fixture with colons in description"
```

---

### Task 2: Write failing test for colon truncation

**Files:**
- Modify: `backend/test/api/profiles.test.js`

- [ ] **Step 1: Write a test that uploads ColonTest.kpro and asserts the full description is preserved**

Add this test inside the existing profile upload `describe` block (after the existing parse tests around line 310):

```javascript
it('should preserve colons in profile_description', async () => {
  const testProfilePath = path.join(__dirname, '../../test_data/kaffelogic/roast-profiles/ColonTest.kpro');
  const metaData = {
    recommendation: 'Test colon parsing',
    recommendation_tags: 'test',
    is_private: false
  };

  const response = await request(app)
    .post('/api/v1/profiles')
    .set('Authorization', `Bearer ${testUserToken}`)
    .attach('profileFile', testProfilePath)
    .attach('meta', Buffer.from(JSON.stringify(metaData)), 'meta.json')
    .expect(201);

  // The full description must survive colons
  expect(response.body.profile_description).toContain('Step 1');
  expect(response.body.profile_description).toContain('Step 2');
  expect(response.body.profile_description).toContain('Step 3');
  expect(response.body.profile_description).toContain('Notes');
  expect(response.body.profile_description).toContain('Use 100g batch');
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && DB_HOST=127.0.0.1 NODE_ENV=test npx jest --testPathPattern profiles.test --verbose -t "colons"`

Expected: FAIL — the description will be truncated after "Step 1" (everything after the second colon is lost).

- [ ] **Step 3: Commit the failing test**

```bash
git add backend/test/api/profiles.test.js
git commit -m "test: add failing test for colon truncation in profile_description"
```

---

### Task 3: Fix backend profile parser (parseProfile)

**Files:**
- Modify: `backend/src/utils/kl-parsers.js:115`

- [ ] **Step 1: Fix the split at line 115**

Replace line 115:
```javascript
        let [key, value] = line.split(":");
```

With:
```javascript
        let colonIndex = line.indexOf(":");
        if (colonIndex === -1) return;
        let key = line.substring(0, colonIndex);
        let value = line.substring(colonIndex + 1);
```

- [ ] **Step 2: Fix the `\r`/`\v` replacement at lines 125-127 to use global regex**

Replace:
```javascript
            profile.profile_description = value
              .replace("\\r", " ")
              .replace("\\v", " ");
```

With:
```javascript
            profile.profile_description = value
              .replace(/\\r/g, " ")
              .replace(/\\v/g, " ");
```

- [ ] **Step 3: Run the colon test to verify it passes**

Run: `cd backend && DB_HOST=127.0.0.1 NODE_ENV=test npx jest --testPathPattern profiles.test --verbose -t "colons"`

Expected: PASS

- [ ] **Step 4: Run the full backend test suite to verify no regressions**

Run: `cd backend && DB_HOST=127.0.0.1 NODE_ENV=test npm test`

Expected: All tests pass (26+ tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/utils/kl-parsers.js
git commit -m "fix: split only on first colon when parsing .kpro fields

profile_description and other fields were truncated when their values
contained colons. Also fix \\r/\\v replacement to use global regex."
```

---

### Task 4: Fix backend roast log parser (parseRoastLog)

**Files:**
- Modify: `backend/src/utils/kl-parsers.js:270`

- [ ] **Step 1: Fix the split at line 270**

Replace line 270:
```javascript
        let [key, value] = line.split(":");
```

With:
```javascript
        let colonIndex = line.indexOf(":");
        if (colonIndex === -1) return;
        let key = line.substring(0, colonIndex);
        let value = line.substring(colonIndex + 1);
```

- [ ] **Step 2: Fix the `\r`/`\v` replacement at lines 280-282 to use global regex**

Replace:
```javascript
            log.profile_description = value
              .replace("\\r", "\r")
              .replace("\\v", "\v");
```

With:
```javascript
            log.profile_description = value
              .replace(/\\r/g, "\r")
              .replace(/\\v/g, "\v");
```

- [ ] **Step 3: Run full backend test suite**

Run: `cd backend && DB_HOST=127.0.0.1 NODE_ENV=test npm test`

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/src/utils/kl-parsers.js
git commit -m "fix: apply same colon-split fix to roast log parser"
```

---

### Task 5: Sync fix to deployment copy

**Files:**
- Modify: `deployment/utils/kl-parsers.js:115` (same change as Task 3 Step 1-2)
- Modify: `deployment/utils/kl-parsers.js:270` (same change as Task 4 Step 1-2)

- [ ] **Step 1: Apply the same 4 changes to `deployment/utils/kl-parsers.js`**

Line 115 — same split fix as Task 3 Step 1.
Lines 125-127 — same regex fix as Task 3 Step 2.
Line 270 — same split fix as Task 4 Step 1.
Lines 280-282 — same regex fix as Task 4 Step 2.

- [ ] **Step 2: Verify deployment file matches backend file**

Run: `diff backend/src/utils/kl-parsers.js deployment/utils/kl-parsers.js`

Expected: No differences (or only expected deployment-specific differences).

- [ ] **Step 3: Commit**

```bash
git add deployment/utils/kl-parsers.js
git commit -m "fix: sync colon-split fix to deployment parser"
```

---

### Task 6: Fix frontend parser

**Files:**
- Modify: `frontend/src/app/services/roast-sync.service.ts:429`

- [ ] **Step 1: Fix the split at line 429**

Replace:
```typescript
      const [key, value] = line.split(':');
      if (!key || !value) continue;
```

With:
```typescript
      const colonIndex = line.indexOf(':');
      if (colonIndex === -1) continue;
      const key = line.substring(0, colonIndex);
      const value = line.substring(colonIndex + 1);
      if (!key || !value) continue;
```

- [ ] **Step 2: Verify frontend builds**

Run: `cd frontend && npm run build`

Expected: Build succeeds with no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/services/roast-sync.service.ts
git commit -m "fix: apply colon-split fix to frontend .kpro parser"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && DB_HOST=127.0.0.1 NODE_ENV=test npm test`

Expected: All tests pass.

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`

Expected: Build succeeds.

- [ ] **Step 3: Verify diff is clean and correct**

Run: `git diff HEAD~6 --stat` to confirm only the expected files were changed.
