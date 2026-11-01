# Customer journey

Lingua Coach is a text-chat language coach. A learner signs in, talks through an onboarding interview, accepts a course roadmap, and then works through it one lesson at a time in chat. Every learner-facing behavior of the coach comes from the skill files in [`apps/backend/skills/`](../../apps/backend/skills/README.md).

## Who the learner is

An adult studying a foreign language toward a concrete outcome (for example "run meetings in Spanish within six months"). They have a native language, a target language, a rough self-assessed level, and a limited amount of time per day. They want a coach that remembers what they got wrong and paces the work for them.

## The whole journey

```mermaid
flowchart TD
  signIn[Sign in with Clerk] --> gate{Onboarding complete?}
  gate -- no --> onboard[Onboarding chat]
  gate -- yes --> dash[Dashboard]
  onboard --> interview[Interview: languages, goal, level, time, focus]
  interview --> roadmap[Coach proposes a course roadmap]
  roadmap --> refine{Learner happy?}
  refine -- Change --> roadmap
  refine -- Accept --> dash
  dash --> start{Lesson in flight?}
  start -- no --> gen[Start lesson: coach writes today's curriculum]
  start -- yes --> resume[Resume lesson]
  gen --> lesson[Lesson chat]
  resume --> lesson
  lesson --> stop[Stop: leave, lesson stays open]
  stop --> dash
  lesson --> finish[Finish lesson]
  finish --> record[Summary, mistakes, pace, reports updated]
  record --> dash
  dash --> reports[Read the four reports]
```

## 1. Sign in

The entry point is the Clerk sign-in page at `/sign-in`. There is no marketing page. After sign-in the app syncs the learner into its own database and routes them:

- to `/onboarding` while no plan has been accepted;
- to `/dashboard` once a plan has been accepted.

## 2. Onboarding interview

The onboarding chat runs the `onboarding_interviewer` skill followed by `course_composer`. The coach asks one question per reply.

1. It starts in English and asks for the native language, then the target language.
2. From then on it speaks the target language and accepts answers in any language.
3. It asks about the goal and horizon, the current level (with a short diagnostic), how many **minutes each lesson** should last and how many lessons per week, skill and topic priorities, constraints (budget, learning style), and motivation. The lesson length is required: there is no default, and a vague answer gets a follow-up asking for a number.
4. When it has enough, it stores a learner profile and proposes a **course roadmap**: goal summary, starting level, target plan days with a range, milestones with success criteria, the lesson length and lessons per week, and the first block of daily themes (grammar, vocabulary, goal context).

The roadmap appears next to the chat as a card with **Accept** and **Change**.

- **Change** keeps the card visible and sends a hidden request to the coach, which asks what to adjust. The learner answers in plain words ("fewer days", "more email writing"), and the coach replies with a revised roadmap that replaces the card.
- **Accept** needs a lesson length in the profile; without one the coach is asked for it first. It saves the roadmap as the learner's plan, creates the Roadmap and 4-Week Plan reports, deletes the onboarding transcript, and opens the dashboard.

## 3. Dashboard

The dashboard is the home screen after onboarding. It shows:

- the main action, which is **Start lesson** when nothing is in flight and **Resume lesson N** when a lesson is open;
- an elapsed-time counter while a new lesson is being generated, with **Check again** if it runs long and **Try again** if it fails;
- a pace strip with plan days done out of the target, the pace state (on pace, behind, or ahead), and the projected completion date;
- a one-line acknowledgment after a lesson was just finished (for example that it was on pace or that the plan moved by a day).

The account menu in the header opens the four reports and signs out.

## 4. Lessons

### Plan days and pacing

- One **plan day** is one finished lesson. Lessons are numbered 1, 2, 3, … and have no calendar date.
- The roadmap sets a **target** number of plan days. The dashboard shows how many are done.
- **On pace** means the lesson was finished within **24 hours** of when it started. The clock starts when the generated lesson becomes active.
- A lesson can stay open across days. Leaving the chat does not stop the clock.
- Finishing **after** 24 hours marks the lesson as slipped. The plan moves one plan day later and the projected completion date shifts. The learner is never blocked from continuing.
- The pace strip says **behind** when the open lesson is past its 24 hours or the last lesson slipped, **ahead** when the last lesson took at most 12 hours and the plan never slipped, and **on pace** otherwise.

### Start

**Start lesson** is available only when no other lesson is generating or open. A learner whose profile predates lesson timing is first asked "How many minutes per lesson?" on the dashboard. The coach writes the curriculum for the next lesson from the accepted roadmap, the learner profile, the last two lesson summaries in full plus a one-line note on the three before, and the most relevant recorded mistakes. A curriculum holds one lesson goal, one grammar focus, one vocabulary theme with the new words, the due mistake patterns to retest, the goal situation for reading and writing, and a few practice targets, sized to the lesson length. Generation takes up to about two minutes. If it fails, or the server restarted while generating, that lesson is marked failed and the learner can start a new one.

### Lesson chat

The lesson chat runs the `exercise_tutor` skill. A lesson lasts the learner's chosen number of minutes. Every exercise is the same chat exchange, so grammar, vocabulary, review of past mistakes, and reading/writing for the goal are mixed in one conversation rather than split into blocks.

- A collapsible **focus card** at the top shows the lesson goal, grammar focus, and vocabulary theme. It collapses once the conversation starts.
- A **time card** shows practice time against the lesson length (for example "8 / 15 min"). It counts active time: a long pause adds at most 5 minutes.
- The coach teaches, then practices: a short explanation and graded exercises for the grammar point, the new words in full format with exercises, a retest of due mistakes in a new context, and a reading or writing task in the goal context. If the learner is fast, the coach makes it harder instead of ending early; after a skip it offers an easier variant of the same item.
- The coach praises specific things done right and corrects mistakes with a one-line rule. Recurring errors are saved as **mistake patterns**, scheduled for review after 1, 3, 7, and then 14 days. A due pattern done right again moves its review further out; done right in two different lessons, it is closed.
- The learner can ask for plan changes in the lesson chat ("make it 60 days", "focus on travel"). The coach applies them to the profile and, for the target plan days, recomputes the projected completion date. There is no separate plan editor.
- In the last minutes the coach gives a short recap and suggests finishing. It never suggests finishing before the lesson time is used.

### Stop and resume

**Stop** returns to the dashboard. The lesson stays open, the transcript is kept, and the 24-hour clock keeps running. **Resume** reopens the same chat with its history.

### Finish

**Finish lesson** is always available while the lesson is open, even before the coach suggests it. It opens a short dialog with an optional free-text note. On finish:

1. The lesson gets a **session summary**: practice minutes against the lesson length, what is now solid and what is still shaky, patterns closed, new mistake patterns, the new words, and the learner's note. Finishing early still counts as a plan day; the dialog says "You practiced 8 of 15 min" and the shortfall is noted in the Progress report.
2. Pace is evaluated against the 24-hour window, and the plan slips by one day if needed.
3. The Progress and Error Log reports are updated by the `report_writer` skill in the background, after the learner is back on the dashboard.
4. The lesson transcript is deleted. The summary, mistakes, and reports are what later lessons read.
5. The learner returns to the dashboard and can start the next lesson.

## 5. Reports

Four markdown reports live under the account menu. They are written by the coach and are read-only for the learner.

| Report | Created | Contents |
|--------|---------|----------|
| Roadmap | On plan accept | Overview, milestones, learning principles, scope notes |
| 4-Week Plan | On plan accept | Block overview, day-by-day themes (grammar, vocabulary, goal context), lesson length and rhythm |
| Progress | After the first finished lesson | Latest session (time practiced, what is solid, what is shaky), a skills table (grammar, vocabulary, reading, writing, goal-specific), and an update log |
| Error Log | After the first finished lesson | Pattern tracker, a daily log of fixes, and a list of confusable words |

After each finished lesson the coach appends dated entries or rewrites whole sections. A report that does not exist yet shows "Fills in after your first lesson".

## What the product does

- Text chat only. The learner types, and the coach answers with a whole message after the learner sends one.
- One lesson in flight at a time.
- Plan changes happen in chat.
- Transcripts are temporary. The onboarding transcript is deleted on accept and a lesson transcript on finish.
- Usage is capped: 60 chat messages per hour and 2 lesson starts per 24 hours per learner, plus global Gemini limits. When a cap is hit the app shows a "try again later" message.

## What the product leaves out

- Voice input, speech output, video, and speaking practice. Lessons train reading and writing.
- A settings screen or plan editor.
- Calendar scheduling and reminders.
- Ratings, thumbs, or other feedback widgets.
- Abandoning a lesson. An open lesson is finished to move on.

## Terms

| Term | Meaning |
|------|---------|
| Learner profile | Languages, goal, level, time budget, focus, constraints, and motivation from the interview |
| Course roadmap | The proposed plan: summary, milestones, weekly template, first block of themes |
| Plan day | One finished lesson |
| Target plan days | Length of the accepted plan in plan days |
| Pace window | 24 hours from lesson start to finish |
| Slip | A lesson finished after the pace window, which moves the plan one day later |
| Curriculum | The generated content of one lesson |
| Session summary | What was done in a finished lesson |
| Mistake pattern | A named recurring error with an example and a review date |
