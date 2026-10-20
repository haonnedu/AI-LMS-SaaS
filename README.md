# Eduvia — AI-Powered Education Platform

> **Smarter Teaching. Better Learning.**

Eduvia is an AI-powered, multi-tenant Education SaaS platform designed to help teachers create educational content, manage classrooms, assess student performance, and personalize learning experiences.

The platform combines **Retrieval-Augmented Generation (RAG)**, Large Language Models (LLMs), intelligent assessment, and automated grading to connect teachers and students in a unified digital learning environment.

**Project Status:** Foundation scaffold / Pre-MVP
**Initial Market:** Vietnam
**Target Users:** Individual teachers, students, educational institutions, and schools
**Business Model:** Subscription-based SaaS (B2C and B2B)
**Working Name:** Eduvia (domain and trademark availability not yet verified)

### Run the foundation

A runnable frontend and backend scaffold is now available. Start with [DEVELOPMENT.md](DEVELOPMENT.md) for setup and verification.

```powershell
.\scripts\setup.ps1
```

Run `.\scripts\dev-backend.ps1` and `.\scripts\dev-frontend.ps1` in separate terminals, then open [Eduvia locally](http://localhost:3000). Docker Compose is also provided for PostgreSQL/pgvector, Redis, migration, API, worker, and frontend.

| Implemented foundation | Next product work |
|---|---|
| Next.js/TypeScript workspace shell and empty states | Identity, authenticated sessions, personal workspaces, RLS |
| FastAPI liveness/readiness, request IDs, environment settings | Document upload, licensed/private RAG, generation |
| Database connection, Alembic bootstrap, Redis/Celery configuration | Classes, enrollments, quizzes, grading, OMR |
| Shared OpenAPI types, locked dependencies, local run scripts, CI | Subscriptions, production deployment, recovery validation |

The foundation does not expose tenant/student data endpoints. The feature catalog below remains the product roadmap; a page or module boundary does not mean its workflow is implemented.

### Design documents

- [ARCHITECTURE.md](ARCHITECTURE.md): module boundaries, workflows, security, deployment, and delivery gates.
- [DATABASE.md](DATABASE.md): canonical entity names, relationships, constraints, access policies, and illustrative SQL.

This README describes the product direction; the two design documents define the proposed implementation. All features below are planned unless explicitly marked complete. The first pilot targets 10–20 teachers, one education level, and one or two subjects. It ends with reviewed teaching materials, online single-choice quizzes, and basic results. OMR follows in phase 4; school administration and advanced AI remain later scope.

---

## 1. Vision

Build an intelligent education ecosystem where teachers spend less time on repetitive administrative tasks and more time teaching, while students receive personalized learning experiences.

### Core Objectives

- Automate lesson planning and educational content creation.
- Generate curriculum-aligned examinations and study guides.
- Provide AI assistance grounded in authorized textbook content.
- Enable students to access learning materials and complete assessments.
- Automatically grade objective examinations using document scanning.
- Analyze student performance and identify learning gaps.
- Support personalized teaching strategies.
- Scale from individual teachers to entire schools.

## 2. User Roles

### 2.1 Platform Administrator

- Manage users and organizations.
- Configure subscription plans and usage limits.
- Monitor system performance and AI usage.
- Manage authorized shared knowledge bases.
- Manage platform settings and billing.

### 2.2 Teacher

- Create and manage classrooms.
- Generate AI-powered lesson plans.
- Generate examinations and study guides.
- Upload private teaching materials.
- Create assignments and quizzes.
- Share educational resources with students.
- Scan and grade paper examinations.
- Track student performance.
- Receive AI-generated teaching recommendations.

### 2.3 Student

- Join classrooms using invitation links or class codes.
- Access teacher-assigned learning materials.
- Complete online quizzes and assignments.
- Take pre-class and post-class assessments.
- View personal grades and feedback.
- Track learning progress.
- Access AI tutoring features when enabled.

### 2.4 School Administrator (Future)

- Manage teachers and school workspaces.
- Assign teachers to departments and classes.
- Manage institutional subscriptions.
- Configure school-specific educational templates.
- View authorized school-level analytics.
- Control permissions and shared resources.

---

## 3. Core Features

### 3.1 AI Lesson Plan Generator

Automatically generate structured lesson plans using curriculum-aligned educational materials.

**Inputs:**

- Subject
- Grade
- Textbook series
- Chapter and lesson
- Teaching duration
- Learning objectives
- Teaching methodology
- Preferred lesson plan template

**Outputs:**

- Learning objectives
- Required materials
- Teaching activities
- Classroom exercises
- Group activities
- Assessment questions
- Teaching notes
- Editable Word/PDF documents

Teachers can customize and save their preferred lesson plan templates.

### 3.2 AI Examination Generator

Generate assessments based on selected curriculum topics and learning objectives.

**Features:**

- Multiple-choice questions
- Short-answer questions
- Essay questions
- Difficulty configuration
- Question banks
- Multiple examination versions
- Answer keys
- Scoring rubrics
- Assessment matrices
- Word/PDF export

Supported assessment types include pre-class quizzes, 15-minute tests, midterm examinations, final examinations, and revision exercises. The first pilot supports single-choice online questions with deterministic scoring. Short-answer and essay authoring, automated grading of written responses, and randomized exam forms are later capabilities; schema placeholders do not imply MVP delivery.

### 3.3 AI Study Guide Generator

Generate structured revision materials from selected textbook chapters and teacher-uploaded resources.

**Features:**

- Chapter summaries
- Key concepts
- Learning objectives
- Practice questions
- Revision worksheets
- Answer explanations
- Exportable study guides

### 3.4 Personalized Teacher AI Assistant

Each teacher has a personalized AI assistant configured using their teaching preferences, curriculum, and private materials.

**Personalization sources:**

- Teacher profile
- Subjects and grades
- Preferred textbook series
- Previous lesson plans
- Uploaded educational documents
- Teaching methodologies
- School-specific templates

The system combines shared curriculum knowledge with authorized teacher-specific knowledge.

Fine-tuning individual models is not required for the initial MVP.

### 3.5 Classroom Management

Teachers can create classrooms and manage student participation.

**Features:**

- Classroom creation
- Student enrollment
- Invitation codes
- Learning material distribution
- Assignment management
- Attendance tracking (future)
- Gradebook
- Student progress monitoring

### 3.6 Student Learning Portal

A mobile-first portal where students can access teacher-assigned educational resources.

**Features:**

- Classroom dashboard
- Lesson materials
- Online quizzes
- Assignment submissions
- Assessment results
- Personalized feedback
- Learning history

Start with a mobile-first responsive web portal. PWA installation and selected offline materials can follow pilot validation; offline quiz submission and native mobile applications are outside the first pilot.

### 3.7 Pre-Class Assessment

Teachers can assign quizzes before classroom lessons.

**Workflow:**

1. Teacher creates a lesson.
2. AI generates preparatory materials and questions.
3. Teacher reviews and publishes the assignment.
4. Students study the materials and complete the quiz.
5. The system grades objective questions.
6. Analytics identify topics requiring additional instruction.
7. AI suggests adjustments to the upcoming lesson.

This enables data-informed teaching before each classroom session.

### 3.8 AI Learning Analytics

Analyze student performance at individual, classroom, and topic levels.

**Metrics:**

- Assignment completion rate
- Average scores
- Question accuracy
- Topic-level performance
- Learning objective mastery estimates
- Pre-test versus post-test improvement
- Student progress over time

AI may recommend additional exercises, revision materials, and teaching activities.

Analytics must distinguish between observed assessment results and AI-generated interpretations. A single short quiz should not be treated as a definitive measure of student ability.

---

## 4. Automated Examination Scanning and Grading

### 4.1 OMR-Based Multiple-Choice Grading

Teachers can print standardized answer sheets and scan completed papers using a mobile device.

**Workflow:**

1. Teacher generates an examination.
2. System generates printable answer sheets.
3. Each sheet contains a QR code and alignment markers.
4. Students complete the examination.
5. Teacher scans answer sheets.
6. OpenCV processes the images.
7. OMR detects marked answers.
8. The grading engine compares answers with the answer key.
9. Ambiguous results are flagged with image evidence for teacher correction.
10. In the first OMR release, a teacher approves every result before it becomes an official grade.

**Technology:** Python, OpenCV, QR code recognition, deterministic grading algorithms.

### 4.2 Handwritten Short-Answer Recognition

A future feature using OCR or Vision AI to recognize handwritten responses.

The system will support manual correction of recognition errors before grading.

### 4.3 AI-Assisted Essay Grading

Use LLMs and teacher-defined rubrics to suggest scores and feedback for written responses.

AI-generated scores are advisory and require teacher approval before becoming official grades.

### 4.4 Batch Grading

Future support for uploading multiple scanned examination papers and processing them asynchronously.

---

## 5. Retrieval-Augmented Generation (RAG)

RAG is a foundational component of Eduvia.

The goal is to generate educational content grounded in relevant, authorized source materials rather than relying solely on general LLM knowledge.

### 5.1 Knowledge Base Structure

```text
Education Level
  └── Grade
       └── Subject
            └── Textbook Series
                 └── Chapter
                      └── Lesson
                           └── Content Chunks
```

### 5.2 Knowledge Sources

**Shared Knowledge Base**

- Licensed textbook content
- Authorized curriculum documents
- Educational standards
- Approved teaching templates

**Private Teacher Knowledge Base**

- Uploaded lesson plans
- Teaching materials
- Custom worksheets
- Personal question banks
- School-specific documents

### 5.3 RAG Pipeline

```text
Document Upload
      |
      v
Document Parsing
      |
      v
Text Extraction
      |
      v
Chunking + Metadata
      |
      v
Embedding Generation
      |
      v
PostgreSQL + pgvector
      |
      v
Workspace, License, and Curriculum Scope
      |
      v
Hybrid Retrieval Within Authorized Scope
      |
      v
Reranking
      |
      v
LLM Generation
      |
      v
Source Verification
      |
      v
Teacher Review
      |
      v
Final Educational Content
```

### 5.4 Metadata Example

```json
{
  "grade": 6,
  "subject": "Mathematics",
  "textbook_series": "Ket Noi Tri Thuc",
  "chapter": "Fractions",
  "lesson": "Introduction to Fractions",
  "page": 12,
  "content_type": "theory",
  "language": "vi",
  "document_version": "2026"
}
```

### 5.5 Retrieval Requirements

- Filter by grade, subject, and textbook series.
- Enforce workspace and license predicates inside retrieval queries before source text leaves the database.
- Support hybrid semantic and keyword search.
- Use reranking where beneficial.
- Return source references where available.
- Detect insufficient supporting context.
- Avoid fabricating textbook citations.
- Support document versioning.
- Prevent private documents from leaking across workspaces.

**Important:** Possession of a textbook PDF does not automatically grant commercial redistribution or AI-processing rights. Eduvia must establish appropriate usage rights for shared educational content.

---

## 6. Multi-Tenant SaaS Architecture

Eduvia uses a shared platform with logically isolated workspaces.

```text
                   Eduvia Platform
                          |
             Authentication & Authorization
                          |
                 Workspace Management
                          |
          +---------------+---------------+
          |               |               |
     Teacher A        Teacher B       School Workspace
          |               |               |
     Private Docs     Private Docs    Shared School Docs
          |               |               |
          +---------------+---------------+
                          |
                    AI Services
                          |
             Shared Authorized RAG
                          |
                  LLM Providers
```

### Workspace Principles

- Each teacher can own a personal workspace.
- Users may belong to multiple workspaces.
- Schools can invite existing teacher accounts.
- Teachers retain access to their personal workspace.
- School resources are shared through explicit permissions.
- Existing personal data is not automatically transferred to school ownership.
- Subscriptions and entitlements are separated from data ownership.

This architecture supports teachers joining a school subscription without requiring a new account or losing personal teaching materials. School billing covers the school workspace; personal-workspace billing stays separate. When school collaboration ships, reusing supported lesson plans and study guides requires an explicit rights-checked copy; other content types need dedicated copy workflows. The school owns its copy, while the teacher retains the original. Cross-workspace live sharing is a future feature.

---

## 7. Technology Stack

| Layer                | Technology                      |
| -------------------- | ------------------------------- |
| Frontend             | Next.js, React, TypeScript      |
| UI                   | Tailwind CSS, shadcn/ui         |
| Backend              | Python, FastAPI                 |
| Database             | PostgreSQL                      |
| Vector Database      | pgvector                        |
| RAG Orchestration    | Application services; LlamaIndex or LangChain optional |
| LLM                  | OpenAI, Claude, or Gemini       |
| Embeddings           | Provider-based embedding models |
| Cache / Queue Broker | Redis                           |
| Background Jobs      | Celery                          |
| Image Processing     | OpenCV                          |
| OCR                  | OCR engine / Vision API         |
| Object Storage       | S3-compatible storage / MinIO   |
| Document Export      | python-docx, PDF generation     |
| Containerization     | Docker                          |
| Reverse Proxy        | Nginx / Cloudflare              |
| Deployment           | VPS or Cloud Infrastructure     |

### High-Level System Architecture

```text
                  Next.js Frontend
                         |
                    FastAPI API
                         |
      +------------------+------------------+
      |                  |                  |
 Authentication     Core Services      AI Services
      |                  |                  |
      |          +-------+-------+          |
      |          |       |       |          |
      |       Lessons  Exams  Classes       |
      |                                  RAG Engine
      |                                      |
      +------------- PostgreSQL ------------+
                         |
                      pgvector

Additional Infrastructure:

Redis + Celery
    ├── Document Processing
    ├── Embedding Generation
    ├── Examination Generation
    ├── Image Scanning
    └── Batch Grading

S3 / MinIO
    ├── Uploaded Documents
    ├── Generated Files
    └── Scanned Answer Sheets
```

---

## 8. Database Design Overview

[DATABASE.md](DATABASE.md) is the canonical schema proposal. The main entity groups are:

| Area | Principal entities |
|---|---|
| Identity and tenancy | users, workspaces, workspace_members, workspace_invites, teacher_profiles |
| Curriculum and authorized sources | curriculum_nodes, knowledge_licenses, workspace_knowledge_entitlements, shared_documents, shared_document_versions, shared_document_chunks |
| Private knowledge and storage | storage_objects, storage_quotas, documents, document_versions, document_chunks |
| AI content | content_templates, content_items, content_revisions, generation_jobs, generation_sources, export_jobs |
| Teaching | classes, class_teachers, class_enrollments, students, assignments, assignment_materials |
| Assessment | questions, question_revisions, question_options, question_objectives, exams, exam_versions, exam_items, exam_item_objectives, answer_keys, quiz_attempts, student_answers |
| Grading and scanning | grading_results, grading_result_items, grades, answer_sheets, scan_jobs, scanned_documents, recognized_answers, grading_reviews |
| Operations and billing | background_jobs, outbox_events, audit_events, subscriptions, subscription_entitlements, usage_buckets, usage_reservations, usage_events, billing_events |

Education levels, school grades, subjects, textbook series, chapters, lessons, and objectives are typed `curriculum_nodes`. The `grades` table stores assessment scores only. Lesson plans and study guides are types of `content_items` with revision history. Progress summaries are derived from assessment records rather than maintained as a second source of truth.

### Important Design Principles

- Use UUID primary keys and non-null workspace IDs for tenant-owned resources.
- Enforce PostgreSQL Row-Level Security and operation-level authorization from the foundation phase.
- Use composite tenant foreign keys to reject cross-workspace relationships.
- Freeze published exam items, answer keys, and objective mappings; later edits create new versions.
- Record submitted responses, grading provenance, teacher overrides, and release decisions.
- Keep student payloads and exports free of unreleased keys and solutions.
- Track durable jobs and usage from the first AI request; integrate payments later.
- Apply explicit retention and deletion workflows to student data and storage objects.

---

## 9. Subscription Model

Initial pricing hypotheses for the Vietnamese market:

| Plan          |  Monthly Price | Target                   |
| ------------- | -------------: | ------------------------ |
| Free          |          0 VND | New teachers             |
| Teacher Basic |     49,000 VND | Individual teachers      |
| Teacher Pro   |     99,000 VND | Active teachers          |
| School        | Custom pricing | Educational institutions |

### Free

- Limited AI document generation
- Basic lesson planning
- Limited quiz creation

### Teacher Basic

- Increased document generation quota
- Lesson plans and examinations
- Basic classroom management

### Teacher Pro

- Higher AI usage limits
- Private document RAG
- Advanced assessment features
- OMR scanning quota
- Learning analytics

### School

- Multiple teacher accounts
- School-managed workspaces
- Shared educational resources
- Centralized administration
- Institution-level reporting
- Custom usage limits

Pricing and quotas must be validated against real teacher demand and operational costs.

---

## 10. MVP Scope

Phases 1–3 form the initial teaching pilot. Phase 4 adds OMR after online assessment is stable; phase 5 covers commercial readiness. Security, privacy preparation, cost controls, and recovery checks begin before the pilot, with deeper reviews before commercial launch.

### Phase 1 — Foundation

- [x] Technical architecture and database design documents
- [ ] User authentication
- [ ] Teacher dashboard
- [ ] Workspace management and tenant isolation/RLS checks
- [ ] Durable jobs, usage metering, quota reservations, and storage limits
- [ ] Baseline privacy, secure uploads, audit, and backup/restore checks
- [ ] Document upload
- [ ] Document parsing
- [ ] RAG knowledge base
- [ ] Source-aware AI responses

### Phase 2 — AI Content Generation

- [ ] Lesson plan generator
- [ ] Examination generator
- [ ] Study guide generator
- [ ] Answer key generation
- [ ] Editable content preview
- [ ] Word/PDF export
- [ ] Document history

### Phase 3 — Classroom and Student Portal

- [ ] Classroom creation
- [ ] Student enrollment
- [ ] Learning material sharing
- [ ] Online single-choice quizzes with server-enforced deadlines and safe feedback release
- [ ] Automatic objective grading
- [ ] Teacher results dashboard
- [ ] Pre-class assessment analytics with explicit denominators and one selected attempt per student
- [ ] Initial 10–20 teacher pilot and end-to-end workflow validation

### Phase 4 — Automated Paper Grading

- [ ] Standardized OMR answer sheets
- [ ] QR code identification
- [ ] Camera-based scanning
- [ ] OpenCV answer detection
- [ ] Automatic score calculation
- [ ] Ambiguous-answer correction and teacher approval of every OMR result
- [ ] Gradebook integration

### Phase 5 — Commercial Launch

- [ ] Subscription plans
- [ ] Usage settlement and billing reconciliation
- [ ] Billing integration
- [ ] Subscription entitlements
- [ ] Security review
- [ ] Performance testing
- [ ] Commercial readiness review using pilot feedback
- [ ] Production deployment

### Future Roadmap

- [ ] Short-answer/essay authoring and randomized exam forms
- [ ] Batch OMR processing
- [ ] PWA installation and selected offline materials
- [ ] AI Tutor for students
- [ ] Handwritten answer recognition
- [ ] AI-assisted essay grading
- [ ] Adaptive learning recommendations
- [ ] School administration portal
- [ ] Parent portal
- [ ] Attendance management
- [ ] Advanced learning analytics
- [ ] School-wide content collaboration
- [ ] Integrations with existing school systems

---

## 11. Security, Privacy, and Compliance

Eduvia processes educational records and may process personal data belonging to minors.

Security and privacy must be designed into the platform from the beginning.

### Requirements

- Role-based access control
- Tenant data isolation
- Secure authentication
- Encrypted transport (HTTPS)
- Secure file storage
- Signed URLs for private resources
- Data access audit logs
- Controlled document sharing
- Data retention policies
- Account and data deletion workflows
- Age-appropriate student access
- Applicable parental or guardian consent mechanisms
- Compliance review under Vietnamese data protection and education requirements

Student grades, learning records, and personal information must not be publicly accessible.

AI-generated grading decisions must be reviewable and correctable by authorized teachers.

---

## 12. Product Differentiation

Eduvia is not intended to be another generic AI chatbot.

Its competitive advantages should focus on:

1. Vietnamese curriculum alignment.
2. Textbook-grounded content generation.
3. Personalized teacher workspaces.
4. Reusable school-specific templates.
5. Integrated teacher and student experiences.
6. Pre-class learning assessments.
7. Automated paper examination grading.
8. Learning analytics and teaching recommendations.
9. A scalable individual-to-school subscription model.

### Core Value Proposition

**For Teachers:** Spend less time preparing, grading, and managing repetitive tasks.

**For Students:** Access structured materials, complete assessments, and receive timely feedback.

**For Schools:** Centralize educational workflows and support data-informed teaching.

---

## 13. Success Metrics

### Product Metrics

- Weekly active teachers
- Monthly active students
- Lesson plans generated
- Examinations generated
- Quiz completion rate
- Scanned papers processed
- Teacher retention rate
- Free-to-paid conversion rate

### AI Quality Metrics

- Curriculum relevance
- Source citation accuracy
- Teacher acceptance rate
- Content correction frequency
- OMR recognition accuracy
- Grading agreement with teacher-reviewed results
- AI generation cost per document

### Business Metrics

- Monthly recurring revenue (MRR)
- Customer acquisition cost (CAC)
- Customer lifetime value (LTV)
- Subscription churn
- Average revenue per paying teacher
- AI infrastructure cost per active user

---

## 14. Development Strategy

The initial product should prioritize a narrow, validated use case rather than attempting to deliver every LMS feature immediately.

**Recommended initial focus:**

- One education level
- One or two subjects
- Authorized curriculum resources
- AI lesson planning
- AI quiz generation
- Student pre-class quizzes
- Basic teacher analytics

OMR scanning should be introduced after the core lesson and assessment workflow is stable.

The first pilot should involve approximately 10–20 teachers to evaluate usability, generated content quality, grading accuracy, and willingness to pay.

---

## 15. Long-Term Vision

Eduvia aims to become an integrated AI education ecosystem supporting the complete teaching and learning lifecycle.

```text
Curriculum & Textbooks
         |
         v
AI Lesson Preparation
         |
         v
Teacher Review
         |
         v
Student Pre-Class Learning
         |
         v
Pre-Class Assessment
         |
         v
AI Learning Analytics
         |
         v
Classroom Teaching
         |
         v
Post-Class Assessment
         |
         v
Automated Grading
         |
         v
Student Progress Tracking
         |
         v
Personalized Learning Recommendations
```

The long-term goal is to help educators understand what students know, what they struggle with, and how to improve learning outcomes.

---

## License

Proprietary — All rights reserved.

The application source code, platform assets, and proprietary services are intended for commercial development. Third-party educational content, AI models, libraries, and textbooks remain subject to their respective licenses and usage rights.

---

**Eduvia — Smarter Teaching. Better Learning.**
