# InsightBridge demo script

**Length:** 6 minutes. **Lead model:** GPT-6 Astra. **Comparison:** saved GPT-5.4 run.

Use the floating **Demo script** panel at the bottom right. It has Previous/Next controls, screen links and saved session progress. Choose **Read full guide** for these presenter notes. The script does not start a model run.

## Before the demo

- Open `https://insightbridge-wev0.onrender.com/`. For local use, start the app with `./start-app.ps1` and open `http://127.0.0.1:8765/`.
- Restart an older local server if it still shows the previous saved results.
- Use **Reset demo** if you want to clear decisions from an earlier rehearsal. Check that no decisions you want to retain are in this browser.
- Keep this script beside the app. Begin on Home.

## 1. Introduce the problem — 30 seconds

**Show:** Home.

**Say:**

“Support tickets tell us what customers experienced. Operating records help explain why it happened. InsightBridge brings these together and proposes the next action. A person reviews that action and decides what to do.”

“We will use seven saved cases: four delivery issues and three item cancellations.”

## 2. Explain the framework — 40 seconds

**Click:** **View AI framework**.

**Show:** Decision rules, model behaviour guidelines, roles and responsibilities, and the evaluation rubric. Keep the explanation brief.

**Say:**

“The framework defines when action is needed, how recommendations should be written, and who should own the work. Astra is an earlier saved run. Opening this current document does not change its analysis.”

“It also defines how we assess the output. We check the facts, the decision, the usefulness of the recommendation, and the clarity of the language.”

Close the document.

## 3. Review a delivery issue — 75 seconds

**Click:** **GPT-6 Astra**. Select the Store A delivery issue. Open **Issue description** if needed.

**Say:**

“At Store A, 24 of 120 evening orders arrived late. That is 20%, above the 15% action threshold.”

“The records point to long waits for a rider after packing. Packing and travel were within their time limits in the reviewed order timelines. The wider cause of the rider wait still needs dispatch expertise.”

Open the supporting records once, if useful. Close them and move on.

**Click:** **Remedial actions**. Show the dispatch recommendation and **What needs to be done**.

**Say:**

“The task is to explain the rider waits and propose a justified next step. It names an owner, sets a priority, and defines the expected result. It does not approve staffing or operating-rule changes.”

## 4. Show restraint — 30 seconds

**Click:** The Store C delivery issue.

**Say:**

“A complaint does not always require another task. This case is below the action threshold. The findings remain visible, but the model proposes no remedial action.”

## 5. Review the engineering recommendation — 60 seconds

**Click:** Store A, **Milk - 500 ml pouch**. Review the issue, then **Remedial actions**.

**Say:**

“Milk stock reached zero at 19:02. Checkout continued accepting orders until the 19:14 update. Six paid orders lost the item.”

“Astra recommends an engineering proposal to stop milk checkout when recorded stock reaches zero. Checkout should not have to wait for the scheduled refresh.”

**Show:** The **What needs to be done** section and **Availability and checkout engineering owner**.

- Propose the design for handling zero stock and valid restocking.
- Test delayed, repeated and out-of-order updates, and checkout speed.
- Measure the time from zero stock to checkout blocking.
- Include a rollback plan and test results.

**Say:**

“This is engineering work because it needs system access, design choices and testing. The customer issue and update gap are already established. The remaining work is to design a safe change. Implementation and rollout need separate approval.”

## 6. Make a decision and open the ticket — 50 seconds

**Show:** Owner, priority and decision controls for the milk design recommendation. Keep the suggested owner and priority unless you have a reason to change them.

**Say:**

“The reviewer can proceed, defer, or reject. A rejection needs a reason. For this example, I will proceed with preparing the design.”

**Click:** **Proceed**. Return Home, open **JIRA tickets**, and open the new ticket.

**Say:**

“The approved recommendation becomes a ticket draft with its scope and acceptance criteria. Multiple tickets stay in a list. Each opens in a narrow, scrollable dialog.”

“This prototype saves decisions in this browser. It does not send tickets to Jira.”

## 7. Compare the models and check the audit — 60 seconds

**Click:** Home → **GPT-5.4**. Revisit the same milk case.

**Say:**

“We can review the same case through another saved model run. Across all seven cases, GPT-5.4 proposed eight recommendations. Astra proposed four. More recommendations do not automatically mean a better result. We should judge whether each task is needed and useful.”

**Click:** Home → **Run trace & cost**. Select each model in turn.

**Say:**

“The audit keeps the original requests, responses, tokens and estimated costs. The new GPT-5.4 run includes a framework-reading call before its case analysis.”

“GPT-5.4 used 88,480 tokens, with an estimated token cost of about 29 cents. Astra used 80,449 tokens, with an estimated cost of about $1.29. Opening these saved results makes no new model calls.”

**Presenter note:** These runs used different framework and prompt versions. Present this as a comparison of two saved outputs, not a controlled model benchmark. Display wording was simplified separately; original model logs remain unchanged. Cost estimates are not provider invoices.

## 8. Close — 15 seconds

**Click:** Home → **Leave feedback**.

**Say:**

“The flow is simple: understand the issue, review the proposed work, and decide what happens next. You can leave a star rating and a short comment here.”

Close the feedback dialog without submitting a rehearsal rating.

## Short answers if asked

| Question | Answer |
|---|---|
| Is this live analysis? | No. The demo replays two saved runs. |
| Is this real customer data? | These are synthetic demo cases with linked support and operating records. |
| Does the framework dialog change the saved analysis? | No. A framework change needs a fresh run to affect results. |
| Did Astra read the latest framework too? | No. It is the earlier saved comparison run. |
| Does Proceed implement the change? | No. It records approval for the stated task and prepares a ticket draft. |
| Where is feedback stored? | Local use writes to `feedback-data/events.jsonl`. The deployed app uses its private persistent Render disk. |
| What is still a human judgment? | Whether the explanation is convincing, the work is necessary, and the proposed change should proceed. |

## Two-minute version

Show Home → framework → GPT-6 Astra → Store A milk issue → remedial action → Proceed → ticket dialog. End with: “The model proposes the work. The reviewer owns the decision. The audit shows how the model reached its output.”
