# Language Tutor — RAG & LangChain Technical Requirements

## 1. Objective

Improve the existing AI language-tutor architecture by introducing:

- **RAG (Retrieval-Augmented Generation)** for dynamic access to teaching knowledge.
- **pgvector** for semantic search while keeping PostgreSQL as the primary database.
- **LangChain** for LLM integration, prompts, retrieval pipelines, tools, and structured outputs.
- **LangGraph** where stateful, branching, or multi-step agent workflows are required.

The goal is to move from a system based mainly on static Markdown skills and large JSON context toward a system that retrieves only the knowledge and learner context relevant to the current task.

---



## 2. Current Architecture

The tutor currently uses Markdown-based skills such as:

- Onboarding Interviewer
- Course Composer
- Exercise Tutor
- Feedback Giver

User information and learning history are stored in PostgreSQL as JSON, including:

- Learning goals
- Target language
- Language level
- Typical mistakes
- Exercise results
- Learning progress

Current conceptual flow:

```text
User
  |
  v
Tutor Agent
  |
  +-- Interviewer.md
  +-- Course Generator.md
  +-- Exercise Generator.md
  |
  v
PostgreSQL JSON context
```



### Current limitations

1. Static Markdown skills provide the same instructions regardless of the learner's current needs.
2. JSON context can grow continuously as the learner completes more exercises.
3. Passing the entire history to the LLM is inefficient and increases context size.
4. There is no semantic retrieval of relevant teaching material.
5. Student history is stored primarily as events rather than a compact representation of current learning state.

---



# 3. Proposed Architecture

Use PostgreSQL for structured learner state and **pgvector** for semantic retrieval of teaching knowledge.

```text
                         FastAPI
                            |
                            v
                     Tutor Service
                            |
              +-------------+-------------+
              |                           |
              v                           v
       PostgreSQL                   pgvector
       structured data             semantic search
              |                           |
              |                    Teaching knowledge
              |                    - Grammar
              |                    - Vocabulary
              |                    - Curriculum
              |                    - Exercises
              |                    - Error patterns
              |                    - Examples
              |
              v
        Student state
              |
              +-------------+
                            |
                            v
                   LangChain / LangGraph
                            |
                            v
                           LLM
                            |
                            v
                 Lesson / Exercise / Feedback
```

---



# 4. Data Architecture

Separate the current JSON context into three conceptual categories.

## 4.1 Student Profile

Keep deterministic user information in PostgreSQL.

Example:

```json
{
  "student_id": 123,
  "target_language": "Spanish",
  "native_language": "English",
  "cefr_level": "A2",
  "goals": [
    "travel",
    "basic conversation"
  ],
  "preferred_topics": [
    "food",
    "culture"
  ]
}
```

This data should **not** be stored primarily in vector search.

It should be retrieved directly using SQL.

---



## 4.2 Student Learning State / Memory

Transform raw exercise history into meaningful learning signals.

Instead of storing only:

```json
{
  "answer": "Yo gusto pizza"
}
```

store structured information such as:

```json
{
  "skill": "verb_gustar",
  "error_type": "incorrect_subject_structure",
  "severity": 0.8,
  "mastery_score": 0.35,
  "last_seen": "2026-08-01"
}
```

Recommended concepts:

- Skill
- Mastery
- Confidence
- Error type
- Error frequency
- Last practiced
- Last failed
- Number of successful attempts
- Recommended review date

Example:

```json
{
  "skills": [
    {
      "skill": "past_tense",
      "mastery": 0.45,
      "weaknesses": [
        "preterite vs imperfect"
      ]
    },
    {
      "skill": "gender_agreement",
      "mastery": 0.25
    }
  ]
}
```

PostgreSQL remains the source of truth for this data.

---



# 5. Teaching Knowledge Base

Convert the existing Markdown knowledge into a structured teaching knowledge base suitable for RAG.

Possible structure:

```text
knowledge/
  curriculum/
    spanish_a1.md
    spanish_a2.md
    spanish_b1.md

  grammar/
    spanish/
      ser_vs_estar.md
      preterite_vs_imperfect.md

  vocabulary/
    travel/
      airport.md
      hotel.md

  exercises/
    grammar/
      fill_blank_patterns.md
      roleplay_patterns.md

  mistakes/
    english_speakers/
      gender_agreement.md
```

These documents should be chunked and embedded into pgvector.

---



# 6. pgvector Requirements

Use PostgreSQL + pgvector rather than introducing a separate vector database initially.

Example schema:

```sql
CREATE TABLE teaching_chunks (
    id UUID PRIMARY KEY,
    content TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(1536)
);
```

Metadata should contain filtering information such as:

```json
{
  "language": "Spanish",
  "level": "A2",
  "type": "grammar",
  "skill": "ser_vs_estar",
  "topic": "travel"
}
```

The exact embedding dimension depends on the selected embedding model.

The vector store should support:

- Semantic similarity search
- Metadata filtering
- Top-K retrieval
- Potential hybrid keyword + vector search
- Versioning of teaching materials where required

---



# 7. RAG Retrieval Flow

When generating a lesson, the system should combine structured student state with semantic teaching knowledge.

Example:

```text
Student
  |
  v
Load profile from PostgreSQL
  |
  v
Load weaknesses / mastery
  |
  v
Determine learning objective
  |
  v
Generate retrieval query
  |
  v
pgvector
  |
  +-- Relevant curriculum
  +-- Grammar explanation
  +-- Similar mistakes
  +-- Exercise templates
  |
  v
LLM
  |
  v
Generate lesson
```

Example retrieval query:

```text
Spanish A2 travel learner struggling with past tense
```

Potential retrieved material:

```text
1. A2 Spanish past-tense curriculum
2. Preterite vs imperfect explanation
3. Travel-related past-tense exercise
4. Common errors made by English-speaking learners
```

Only the relevant chunks should be passed to the LLM.

---



# 8. Hybrid Retrieval

Do not rely exclusively on vector search.

Use:

```text
SQL
+
Vector Search
+
Application Logic
```

For example:

### SQL

Determine:

```text
Student = 123
Level = A2
Goal = Travel
Weakness = Past tense
```



### pgvector

Retrieve:

```text
A2 + travel + past tense teaching material
```



### Application logic

Determine:

```text
Today's objective = practice past tense
```



### LLM

Generate the lesson from the selected context.

This provides more predictable behavior than allowing an agent to search everything autonomously.

---



# 9. LangChain Responsibilities

Use LangChain as the LLM application/orchestration layer, not as the database itself.

LangChain should provide:

- LLM integrations
- Prompt templates
- Structured output
- Retrieval interfaces
- Tool calling
- Chains/pipelines
- Streaming
- Agent capabilities
- Evaluation integration where appropriate

Example conceptual implementation:

```python
student = db.get_student(student_id)

memory = db.get_learning_memory(student_id)

query = f"""
Language: {student.language}
Level: {student.level}
Goal: {student.goal}
Weaknesses: {memory.weaknesses}
"""

teaching_context = retriever.invoke(query)

response = lesson_chain.invoke({
    "student": student,
    "memory": memory,
    "context": teaching_context
})
```

---



# 10. LangGraph Responsibilities

Use LangGraph when the tutor requires more complex stateful workflows.

Potential workflow:

```text
Start
  |
  v
Load Student State
  |
  v
Determine Learning Objective
  |
  +---- Review existing weakness
  |
  +---- Teach new skill
  |
  +---- Practice
  |
  v
Generate Exercise
  |
  v
Evaluate Answer
  |
  v
Update Student Memory
  |
  v
End
```

LangGraph is particularly appropriate for:

- Branching workflows
- Loops
- Retries
- Persistent state
- Human-in-the-loop processes
- Multi-step agents
- Multiple specialized agent nodes

Simple RAG generation does not require LangGraph.

---



# 11. Proposed Tutor Components

Evolve the current Markdown skill model toward explicit application components:

```text
Tutor Orchestrator
       |
       +-- Student Analyzer
       |
       +-- Curriculum Planner
       |
       +-- Knowledge Retriever
       |
       +-- Lesson Generator
       |
       +-- Exercise Generator
       |
       +-- Answer Evaluator
       |
       +-- Memory Updater
```

The Markdown files can remain as instructional resources initially, but their contents should gradually be separated into:

- System instructions
- Teaching knowledge
- Exercise templates
- Curriculum knowledge
- Error patterns

---



# 12. Example End-to-End Flow

User:

> I want to learn Spanish for traveling. I'm A2 and struggle with past tense.



### Step 1 — Load profile

PostgreSQL:

```text
Language: Spanish
Level: A2
Goal: Travel
```



### Step 2 — Load learning state

PostgreSQL:

```text
Past tense mastery: 0.45
Gender agreement mastery: 0.70
```



### Step 3 — Determine objective

Application logic / tutor agent:

```text
Today's objective:
Practice past tense in travel situations.
```



### Step 4 — Retrieve knowledge

pgvector retrieves:

```text
A2 past tense curriculum
Preterite vs imperfect explanation
Travel conversation examples
Past-tense exercise templates
```



### Step 5 — Generate lesson

LangChain assembles:

```text
System instructions
+
Student profile
+
Learning state
+
Retrieved teaching knowledge
```

and sends it to the LLM.

### Step 6 — Evaluate

After the exercise:

```text
User answer
   |
   v
Evaluator
   |
   v
Detected:
preterite/imperfect confusion
```



### Step 7 — Update memory

PostgreSQL:

```text
past_tense.mastery = 0.39
past_tense.error_frequency += 1
```

The next retrieval will therefore prioritize relevant past-tense material.

---



# 13. Key Design Principle

Do **not** replace PostgreSQL with RAG.

Do **not** put all user data into embeddings.

Instead:

```text
PostgreSQL
= "What do we know about this learner?"

pgvector
= "What teaching knowledge is relevant?"

LangChain
= "How do we connect models, prompts, retrieval and tools?"

LangGraph
= "How do we control a complex multi-step tutor workflow?"
```

This separation should be maintained throughout the architecture.

---



# 14. Recommended Technology Stack

```text
API:
FastAPI

Primary database:
PostgreSQL

Vector search:
pgvector

LLM orchestration:
LangChain

Complex agent/workflow orchestration:
LangGraph

Embeddings:
OpenAI embeddings or another suitable embedding provider

Object/document storage:
S3-compatible storage where necessary

Monitoring:
Prometheus + Grafana

LLM tracing/evaluation:
LangSmith or custom evaluation infrastructure
```

---



# 15. Implementation Roadmap



## Phase 1 — Refactor learner data

- [ ] Keep PostgreSQL as the primary database.
- [ ] Separate student profile from learning history.
- [ ] Create structured `student_skills` / mastery data.
- [ ] Create structured error records.
- [ ] Keep raw exercise results for auditing and analytics.



## Phase 2 — Build teaching knowledge base

- [ ] Review existing Markdown skills.
- [ ] Separate instructions from teaching knowledge.
- [ ] Organize curriculum, grammar, vocabulary, exercise templates and error patterns.
- [ ] Add metadata such as language, CEFR level, skill and topic.



## Phase 3 — Introduce pgvector

- [ ] Install/configure pgvector.
- [ ] Create `teaching_chunks` table.
- [ ] Chunk teaching documents.
- [ ] Generate embeddings.
- [ ] Store embeddings and metadata.
- [ ] Implement similarity search.
- [ ] Add metadata filtering.



## Phase 4 — Add LangChain RAG

- [ ] Implement retriever abstraction.
- [ ] Build retrieval queries from student state.
- [ ] Create prompt templates.
- [ ] Pass retrieved context to lesson/exercise generators.
- [ ] Add structured output validation.



## Phase 5 — Improve tutor orchestration

- [ ] Introduce LangGraph where workflows require branching or persistent state.
- [ ] Add explicit learning-objective selection.
- [ ] Add exercise evaluation.
- [ ] Automatically update learner mastery.
- [ ] Feed updated mastery into future retrieval.



## Phase 6 — Evaluate the system

Measure:

- Retrieval relevance
- Answer correctness
- Exercise quality
- Difficulty appropriateness
- Hallucination rate
- Learning progression
- Regression after prompt/model changes
- Latency
- LLM/API cost

The ultimate goal is not simply "better RAG", but **better learner outcomes through accurate personalization**.