# Buy or Wait? — Hybrid AI Financial Decision System

A portfolio version of my submission for **HackerRank Orchestrate — September 2026**, built for the **“Buy or Wait?”** challenge.

The system decides whether a requested purchase is financially safe **now**, should be **delayed**, should use a **partial/installment plan**, or requires **allowed spending changes** first. It combines LLM-based evidence interpretation with deterministic financial simulation and rule-based plan selection.

## 🏆 Result

* **Global Rank:** #496 / 3,062
* **Egypt Rank:** #2
* **Event:** HackerRank Orchestrate — September 2026

\---

## The Challenge

A purchase decision cannot be made from the user’s current balance alone.

The system has to combine information from:

* financial profiles
* historical, pending, and scheduled financial events
* messages that may update or cancel those events
* linked images containing missing financial information
* exchange rates
* seller/request payment options
* the user’s accepted payment methods
* minimum-balance constraints
* spending categories the user is willing or unwilling to change

For every purchase request, the output must determine:

* how much can safely be paid
* whether the purchase is affordable now, later, with a plan, or not affordable
* the recommended payment method
* the payment schedule
* the earliest safe date for full payment
* whether spending changes are required
* a concise explanation of the recommendation

\---

## Architecture

I used a **hybrid architecture** rather than asking an LLM to make the full financial decision.

```text
Input CSVs + Media
        ↓
Load \& Normalize Request Context
        ↓
Image Preprocessing
        ↓
LLM Event Repair from Images
        ↓
LLM Message-Based Event Updates / Deletes
        ↓
Currency Conversion
        ↓
90-Day Financial Calendar
   ├── Known future events
   └── Inferred recurring events
        ↓
Deterministic Balance Simulation
        ↓
Generate Legal Payment Plans
        ↓
Simulate + Filter Safe Plans
        ↓
If needed: Test Allowed Spending Changes
        ↓
Rank Valid Plans
        ↓
LLM-Assisted Final Explanation
        ↓
output.csv
```

The LLM handles **unstructured evidence and explanation**, while the actual affordability decision is driven by deterministic code.

\---

## How the Pipeline Works

### 1\. Load the request context

The program loads the required CSV files from `dataset/` and gathers the data relevant to each request:

* financial profile
* financial events
* messages
* payment options
* exchange rates
* linked media

### 2\. Preprocess image evidence

Images are preprocessed before being passed to the model, including handling files whose actual image format does not match their extension.

Processed images are stored under:

```text
dataset/media/preprocessed\_images/
```

### 3\. Repair incomplete financial events

If an event is missing information that can be recovered from linked image evidence, the LLM is used to fill the missing fields.

The result is returned as structured data and validated before being used. If the repair fails, the original event is preserved rather than allowing the request pipeline to crash.

### 4\. Apply message-based event updates

Messages are treated as evidence that may:

* update an existing event
* correct an amount or date
* cancel/delete an event

The LLM extracts the proposed update, but the update is validated before it is applied to the financial timeline.

### 5\. Normalize currencies

Cash events are converted into the user’s home currency using the supplied exchange-rate data so that later simulation works on a consistent monetary basis.

### 6\. Build a 90-day financial calendar

The system builds a daily calendar from the request date through the next 90 days.

It first inserts explicit future events such as:

* scheduled events
* pending debits

Then it infers likely future recurring events from settled historical cash flow.

### 7\. Infer recurring events

The recurrence logic groups similar settled events and looks for repeated timing patterns in their history.

The implemented logic:

* only considers settled cash events of supported types
* requires multiple historical observations before forecasting
* checks calendar-month-shaped patterns before ordinary day-gap patterns
* detects repeated date intervals from historical gaps
* ignores stale patterns that appear to have stopped
* avoids duplicating a forecast when an equivalent known future event already exists
* estimates the forecast amount from recent observations
* projects the detected pattern into the 90-day window

This forecast is then combined with explicit future events before affordability is evaluated.

### 8\. Simulate future balances

The financial simulator walks through the calendar in date order and applies all credits and debits.

Importantly, the minimum-balance check is performed **after all events on the same day have been processed**, rather than after each individual event.

The simulation tracks:

* projected balance by date
* lowest projected balance
* whether the minimum balance is ever violated
* the earliest date at which a payment becomes safe

### 9\. Generate legal payment plans

The system does not assume every payment method is available.

It builds candidate plans only from methods that are both:

1. accepted by the user, and
2. allowed by the request/seller data

Candidate strategies include:

* full payment now
* waiting and paying in full later
* partial payment
* installments

Each strategy has its own construction and validity rules.

### 10\. Evaluate and rank plans

Every legal plan is simulated against the same 90-day calendar.

If a plan causes the balance to fall below the required minimum at any point, it is rejected.

Safe plans are collected and ranked using the challenge’s decision rules.

### 11\. Test spending changes when necessary

If no plan is safe without changing spending, the system generates only spending changes allowed by both:

* the user’s preferences/protected categories
* the individual event’s flexibility rules

It then tests each valid spending-change set against each legal payment plan, simulates the resulting timeline, and chooses the best safe combination.

### 12\. Generate the explanation

After the final plan has already been selected, the LLM generates a concise explanation grounded in that structured decision.

If explanation generation fails, the system can fall back to a deterministic explanation so the financial result itself is not lost.

\---

## Why Hybrid AI + Deterministic Logic?

I intentionally avoided letting the LLM calculate affordability directly.

### LLM responsibilities

* interpret image evidence
* interpret message evidence
* return structured event updates
* generate the final natural-language explanation

### Deterministic responsibilities

* currency conversion
* recurrence forecasting
* 90-day calendar construction
* balance simulation
* minimum-balance safety checks
* payment-method legality
* payment-plan construction
* spending-change validation
* plan ranking
* final structured output

This made the core decision process inspectable and reproducible while still using an LLM where unstructured information needed to be understood.

\---

## Main Limitation \& What I Would Improve

The main limitation of my submission was the **recurring-event forecasting logic**.

Future affordability depends heavily on what the system predicts will happen over the next 90 days. My implementation inferred recurrence using hand-written rules over historical event groupings, date gaps, recent amounts, stale-pattern checks, and duplicate prevention.

That approach worked well for clear recurring patterns, but real transaction histories are not always perfectly regular. A small mistake in deciding **whether an event is recurring, when it will recur, or what amount to forecast** propagates through the entire balance simulation and can change the calculated safe amount or selected payment plan.

If I had more time, this is the part I would redesign first. I would experiment with a stronger recurrence-prediction layer that considers the event history more holistically, potentially using an LLM to help infer whether a sequence represents a real recurring commitment and what its likely next occurrence is—then validate those predictions before allowing them into the deterministic financial simulator.

I would compare that approach against the current rule-based forecaster on a dedicated recurrence test set rather than changing the rest of the decision pipeline, since the recurrence forecast was the main weak point rather than the overall architecture.

\---

## LLM Usage

The default model used in the submission was **GPT-4o-mini**.

|Step|Purpose|Fallback|
|-|-|-|
|Image event repair|Recover missing financial-event information from linked images|Keep the original event|
|Message event updates|Extract validated event updates/deletes from messages|Keep the existing events|
|Decision explanation|Explain the already-selected structured plan|Deterministic explanation|

Rate-limit failures are retried before falling back.

\---

## Output

The generated `output.csv` contains one row per purchase request:

```text
request\_id
amount\_safe\_to\_pay
affordability\_status
recommended\_payment\_method
payment\_plan
earliest\_date\_for\_full\_payment
spending\_changes\_needed
decision\_explanation
```

\---

## Core Project Structure

```text
code/
├── main.py
├── resolver.py
├── event\_calendar.py
├── balance\_simulation.py
├── payment\_plans.py
├── plan\_evaluator.py
├── spending\_changes.py
├── decision\_explanation.py
├── settings.py
├── requirements.txt
└── evaluation/
    └── main.py
```

The project is intentionally split so that evidence interpretation, forecasting, simulation, plan construction, and plan evaluation can be reasoned about separately.

\---

## Tech Stack

* **Python**
* **OpenAI API**
* **LangChain / ChatOpenAI**
* **Pydantic**

\---

## Running the Project

Install the dependencies:

```bash
pip install -r code/requirements.txt
```

Create a `.env` file in the repository root:

```env
OPENAI\_API\_KEY=your\_api\_key\_here
```

Run the main pipeline:

```bash
python code/main.py
```

Run the sample evaluator:

```bash
python code/evaluation/main.py
```

\---

## What I Learned

The biggest lesson from this challenge was that adding an LLM is only one part of building a reliable AI system.

Most of the engineering work was in deciding **which parts should use AI and which parts should remain deterministic**. The final pipeline separates interpretation from financial policy: models extract information from messy evidence, while ordinary code owns the calculations, constraints, simulation, and plan selection.

The recurrence problem also showed me how strongly one forecasting assumption can affect an entire downstream decision system. Improving the prediction layer without losing deterministic safety would be the main direction I would explore next.

\---

## Notes

This repository is a portfolio version of my HackerRank Orchestrate submission.

Credentials, private evaluation material, and challenge assets that should not be redistributed are intentionally excluded.

