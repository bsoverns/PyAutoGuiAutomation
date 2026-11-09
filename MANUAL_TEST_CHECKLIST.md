# Manual test checklist

These steps need a real desktop and a person. Automated tests cannot cover them.

**Use a harmless target such as Notepad (an empty, unsaved document).** Never point a test at a program with unsaved work, a browser with open accounts, or anything where a stray click or keystroke does damage. Keep one hand near the mouse for the abort steps.

Setup: in Git Bash, `cd` to the repo, activate `.venv`, and run `pip install -e ".[dev]"`. Use a scratch folder for saved tests, for example `automations/`.

Record the Windows version, the number of monitors, and the display scaling you are testing on.

## 1. Launch the builder (AC1)

- [ ] Run `guiautomation gui`. Expected: the builder window opens with an empty step list.
- [ ] Close it and run `python -m guiautomation gui`. Expected: same result.
- [ ] Run `guiautomation gui automations\missing.json`. Expected: an error message, exit code 2, no window.
- [ ] Run `guiautomation gui` with a saved test as the argument. Expected: the steps are listed.

## 2. Add, edit, delete and reorder steps (AC1, AC2)

For each type below, add a step, fill in the fields, then open it again to edit it. Expected: the list shows a readable description and the edit form shows the values you saved.

- [ ] click
- [ ] double click
- [ ] right click
- [ ] move
- [ ] drag (start and end point)
- [ ] type text (literal text)
- [ ] type text from an environment variable (see section 11)
- [ ] press key (for example `enter`)
- [ ] hotkey (for example `ctrl+a`; also try the comma form)
- [ ] scroll
- [ ] wait seconds
- [ ] wait for image
- [ ] assert image visible

Then:

- [ ] Enter a bad value (for example text in a number field, or a missing required field). Expected: a clear error message and the step list is unchanged.
- [ ] Select a step and move it up and down. Expected: the order changes; at the top and bottom the move does nothing.
- [ ] Add a step with a step selected. Expected: it goes after the selection.
- [ ] Delete a step. Expected: it is removed and a sensible neighbour is selected.
- [ ] Save, close, reopen the file. Expected: all steps are the same, in the same order.

## 3. Capture a region (AC3)

- [ ] On a new, unsaved test, add a click step and press **Clip from screen**. Expected: no file dialog; the builder hides and a dim overlay covers the whole screen.
- [ ] Drag a region around a Notepad button or title. Expected: the overlay closes, the builder returns, and the step shows an image path under `images/` next to the test file.
- [ ] The clip appears as a preview in the step editor, and the button now says **Replace clip**.
- [ ] Press **Clip a click** in the main window and drag a region. Expected: a click step is added with no dialog.
- [ ] Select a step and press **Replace clip**. Expected: the target changes and the step's other settings stay.
- [ ] Use **Edit / replace** to change a step's text, then its type. Expected: it changes in place, in the same position.
- [ ] Clip on an unsaved test, then save it elsewhere and reopen it. Expected: the clips are in `images/` next to the test.
- [ ] Press Clip from screen then Esc. Expected: nothing is captured and the builder returns unchanged.
- [ ] Make a tiny accidental drag (a few pixels). Expected: it is ignored, no image is saved.
- [ ] Drag from right to left and bottom to top. Expected: the region is still captured correctly.
- [ ] Open the saved PNG. Expected: it shows exactly the area you selected, and not the builder window or the overlay.
- [ ] Use the same method for wait for image and assert image visible steps.
- [ ] Check that the image file is not tracked: `git status` must not list it.

## 4. Guided run (AC5)

Build a short test: click in Notepad, type `hello`, press Enter, wait 1 second.

- [ ] Start a guided run. Expected: the builder hides or moves aside, and the first step runs.
- [ ] After each step a prompt asks Pass, Fail or Stop. Expected: the step has really happened in Notepad before you are asked.
- [ ] Answer Pass on every step. Expected: a results screen shows all steps passed.
- [ ] Run again and answer Fail on step 2. Expected: the run stops, step 2 is marked failed, later steps do not run.
- [ ] Run again and answer Stop on step 2. Expected: the run ends as aborted.
- [ ] After each of these runs, the builder window is back, visible and usable (not left hidden).

## 5. Real clicks and typing (AC2, AC7)

- [ ] Click step on a Notepad coordinate. Expected: the click lands where the step says (for example the text area gains focus).
- [ ] Double click on a word. Expected: the word is selected.
- [ ] Right click in the text area. Expected: the context menu opens.
- [ ] Drag across text. Expected: the text is selected.
- [ ] Scroll in a long document. Expected: it scrolls in the right direction.
- [ ] Type text `Hello, World 123`. Expected: exact text appears.
- [ ] Type non-ASCII text such as `Grüße café naïve 日本語 😀`. Expected: exactly the same characters appear, in the same order.
- [ ] Type text with a line break (a newline). Expected: Enter is pressed and a new line starts.
- [ ] Press key `enter`, then hotkey `ctrl+a`. Expected: a new line, then everything selected.
- [ ] Add a press key step and pick **Windows key (win)** from the Key list. Expected: the field shows `win`; when run, the Start menu opens. Press Esc to close it.
- [ ] Add a hotkey step, pick **Windows key (win)** from **Add a key**, then type `+d`. Expected: the field shows `win+d`; when run, the desktop is shown. Run it again to restore the windows.
- [ ] Add a hotkey step, type `ctrl`, then pick **Shift** and **Esc** from **Add a key**. Expected: the field shows `ctrl+shift+esc`; when run, Task Manager opens.
- [ ] Type `Windows` in the Key field of a press key step and save. Expected: the step list shows `win`.
- [ ] Click a captured image target. Expected: the click lands on the centre of the matching area.
- [ ] Wait for image: show the target after 3 seconds. Expected: the step passes once it appears. With a target that never appears and a short timeout: the step fails, and the output names the step.
- [ ] Assert image visible with the image present, then absent. Expected: passes, then fails.
- [ ] Check the clipboard before and after typing text. Expected: the clipboard is unchanged.

## 6. Delay and no-delay runs from the command line (AC6, AC7)

Use a test with a click or type step into Notepad, so you can see when it starts.

- [ ] `guiautomation run automations\test.json`. Expected: "Starting in 5 s" is printed, nothing happens for about 5 seconds, then the steps run.
- [ ] `guiautomation run automations\test.json --delay 2`. Expected: about a 2 second wait.
- [ ] `guiautomation run automations\test.json --no-delay`. Expected: the steps start at once.
- [ ] Use `--delay -1`, `--delay abc`, and `--delay 1 --no-delay`. Expected: a usage error, exit code 2, nothing runs.
- [ ] Check `echo $?` after a passing run (0), a run with a failing step (1), a missing file (2), an aborted run (3).
- [ ] Run a test with a deliberately failing step. Expected: the output names the step and the reason.
- [ ] Export a test to a `.py` file and run it with no option, with `--delay 2` and with `--no-delay`. Expected: same delay behaviour and exit codes as above.
- [ ] Open the exported `.py` file. Expected: it contains no secret values.

## 5a. If the image is not found

- [ ] Set a click step to **Stop the run as failed** with a target that is not on screen. Expected: after its timeout the run stops and names the step.
- [ ] Set it to **Keep looking until found** and hide the target. Expected: the run waits past the timeout; when you show the target, it clicks it.
- [ ] Set it to **Keep looking until found** and press Ctrl+Alt+Shift+Q while it waits. Expected: the run ends as aborted.

## 5b. Step names

- [ ] Give a step a name. Expected: it leads that line in the step list.
- [ ] Press **Clip a click**. Expected: after the clip it asks for a name; leaving it blank still adds the step.
- [ ] Press **Run**. Expected: the status window names each step as it runs, and the results list the names.

## 6a. Looping

- [ ] Set **Repeat (times)** to 3 and press **Run**. Expected: a 5 second wait, three loops, and the status window counts them; the results say 3 loops completed.
- [ ] Tick **Forever** and press **Run**, then press Ctrl+Alt+Shift+Q, or **Stop** in the status window. Expected: it stops and the builder comes back.
- [ ] Save and reopen the test. Expected: the Repeat setting is restored.
- [ ] Make a step fail partway through a loop. Expected: looping stops and the failing step is named.
- [ ] `guiautomation run automations\test.json --repeat 3 --no-delay`, then `--forever`. Expected: 3 loops, then loops until stopped with exit code 3.

## 7. Called from another program (AC7)

- [ ] From a different Python script run `from guiautomation import run_automation; r = run_automation("automations\\test.json"); print(r.passed, r.summary())`. Expected: it starts at once (no 5 second wait), and `passed` is True or False to match the outcome.
- [ ] From a batch file or Git Bash script, run `guiautomation run test.json --no-delay`, then test `%ERRORLEVEL%` (or `$?`). Expected: the exit code matches the result.
- [ ] Call it from a CI-style harness or Task Scheduler if you have one. Expected: it behaves the same, and the exit code reaches the caller.
- [ ] Call it with a missing image file. Expected: a clear error, exit code 2, no input is sent.

## 8. Abort hotkey (AC9)

Use a long test with waits (for example wait 30 seconds, then type text in Notepad).

- [ ] Start the run and press **Ctrl+Alt+Shift+Q** during the start delay. Expected: nothing runs, exit code 3.
- [ ] Press the hotkey during a wait step. Expected: the run ends within about a second, exit code 3, nothing is typed afterwards.
- [ ] Press the hotkey between two steps. Expected: later steps do not run.
- [ ] Press the hotkey while a long text is being typed. Expected: typing stops partway.
- [ ] Press the hotkey during a drag step. Expected: the run ends, and the mouse button is not left held down (move the mouse afterwards and check nothing is still being dragged).
- [ ] Press the hotkey during a wait for image. Expected: the run ends.
- [ ] Press only three of the four keys. Expected: nothing happens.
- [ ] Press the hotkey in a guided run while a prompt is open. Expected: the run ends as aborted.

## 9. Failsafe corner (AC9)

- [ ] During a wait step, move the mouse to the top-left corner of the **primary** monitor. Expected: the run ends as aborted, exit code 3.
- [ ] Repeat for the other three corners of the primary monitor.
- [ ] Repeat during the start delay. Expected: the run ends before the first step.
- [ ] Repeat during a drag step, and while text is being typed. Expected: the run ends and the mouse button is released.
- [ ] Make a step that clicks exactly at a corner. Expected: the failsafe triggers and the run is aborted.
- [ ] Move to a corner of a **secondary** monitor. Expected: it is not treated as a failsafe (see README).
- [ ] Move to a corner during a guided run while the Pass/Fail prompt is open. Expected: the run ends as aborted.

## 10. Multiple monitors and scaling (AC8)

Test with at least two monitors if you can. Repeat the key checks for each layout you have.

- [ ] Secondary monitor to the **right** of the primary: capture a region on it. Expected: the saved PNG shows that area.
- [ ] Secondary monitor **left of** the primary (negative X): capture a region on it, then run a click on that image. Expected: the click lands on the right spot.
- [ ] Secondary monitor **above** the primary (negative Y): same checks.
- [ ] Drag a capture region that spans two monitors. Expected: one image covering both parts, with no gap or shift.
- [ ] A click step with fixed coordinates on the left or upper monitor (negative values). Expected: it clicks the right place.
- [ ] Mixed scaling (for example 100% on one monitor, 150% or 200% on the other): capture a region on each, then run the click. Expected: the capture matches what was on screen, and clicks land on the target, with no offset or size change.
- [ ] Wait for image with the target on a secondary monitor. Expected: it is found.
- [ ] Move the target window between monitors. Expected: the step still finds it.
- [ ] Capture overlay with several monitors: it covers all of them, and Esc closes it.
- [ ] Change the monitor layout or scaling, restart the tool, and repeat one capture. Expected: still correct.

## 11. Window handling and secrets (AC3, AC5, AC9)

- [ ] During a capture the builder is hidden, and after capture or Esc it is visible again.
- [ ] After a normal run, a failed run, an aborted run and a guided run, the builder is visible, in front and usable.
- [ ] The builder is not captured in the screenshots it takes (no builder window in the PNG).
- [ ] Set an environment variable (for example `$env:MY_TEST_PASSWORD = 'Sample123'` in PowerShell, or `export` in Git Bash) with a harmless sample value. Add a type text step using that variable name.
- [ ] Run the test. Expected: the value is typed into Notepad, and it does not appear in the output, in the log, or on the clipboard.
- [ ] Open the saved `.json` file in a text editor and search for the value. Expected: only the variable name is stored.
- [ ] Export to `.py` and search it for the value. Expected: not found.
- [ ] Run again with the variable unset. Expected: the step fails, naming the variable, and typing nothing.
- [ ] Try to save a literal text step such as `password=hunter2`. Expected: it is rejected with a clear message.
- [ ] Run `git status`. Expected: no `automations/` files, screenshots or `.env` appear as files to add.
