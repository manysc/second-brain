# Software Architecture Blueprint

This document details the **Clean Architecture** patterns, implementation specifics, and structural rules governing this codebase. 

---

## 1. Directory Structure & Map
Every component must reside strictly within its designated layer. 

```text
src/
├── Domain/               # Enterprise Core (Pure logic, Zero dependencies)
│   ├── Entities/         # Domain models with rich behavior
│   └── ValueObjects/     # Immutable domain attributes
├── Application/          # Business Orchestration
│   ├── Interfaces/       # Contracts for infrastructure (DB, APIs)
│   ├── UseCases/         # Application workflow/interactor logic
│   └── DTOs/             # Flat structures for boundary data crossing
├── Infrastructure/       # Technical Machinery
│   ├── Persistence/      # DB Context, Repositories, Migrations
│   └── ExternalServices/ # Third-party API clients, Message brokers
└── Presentation/         # Delivery Mechanisms
    ├── Controllers/      # HTTP Endpoints (or minimal APIs/Routes)
    └── Middleware/       # Web-specific cross-cutting concerns
```

---

## 2. Layer Definitions & Strict Boundaries

### 🛡️ Domain Layer
- **Purpose:** Houses core business entities, invariants, and enterprise logic.
- **Dependency Rule:** **Strictly Isolation.** Must have zero reference to external libraries, frameworks (e.g., ORMs like EF Core or Prisma), or outer layers.
- **Allowed Imports:** Only native language utilities and types.

### ⚙️ Application Layer
- **Purpose:** Defines the orchestration of domain workflows (Use Cases).
- **Dependency Rule:** Can only import from the **Domain** layer. Outer layers are invisible to it.
- **Abstraction Rule:** Implements the *Dependency Inversion Principle*. It declares interfaces (e.g., `IUserRepository`), but does not know *how* they are implemented.

### 💾 Infrastructure Layer
- **Purpose:** Implements the interfaces defined in the Application layer, managing database drivers, file systems, network calls, and identity management.
- **Dependency Rule:** Knows about Application and Domain layers. 
- **Leaking Prevention:** Types specific to databases or external libraries must be mapped to clean Application DTOs or Domain Entities before crossing back over the boundary.

### 🌐 Presentation Layer
- **Purpose:** Receives user inputs (HTTP, gRPC, CLI) and transforms them into a readable output.
- **Dependency Rule:** Depends directly on Application to trigger workflows. It must never bypass the Application layer to speak directly to Infrastructure or the database.

---

## 3. Data Flow Patterns
To keep boundaries clean, use distinct models as data transitions between boundaries:

1. **Request Received:** Presentation maps incoming JSON/Payload to an Application **DTO**.
2. **Execution:** Presentation passes the DTO to an Application Use Case.
3. **Domain Interaction:** The Use Case requests a **Domain Entity** from an Infrastructure-provided repository interface.
4. **Business Logic Execution:** Domain logic updates the Entity state safely.
5. **Persistence:** Use Case passes the updated entity back to the repository interface to save.
6. **Response Sent:** Use Case returns a flat DTO to Presentation, which wraps it in a JSON envelope.

---

## 4. Implementation Invariants & Guardrails
- **Validation:** Input structure validation happens at the Presentation/Application boundary (e.g., FluentValidation, Zod). Deep business rule validation must be embedded strictly within Domain Entities.
- **Exceptions:** Catch technical errors (e.g., `SqlException`) inside the Infrastructure layer and rethrow them as meaningful, tech-agnostic Domain or Application exceptions (e.g., `EntityNotFoundException`).
- **State Changes:** Domain entities should avoid public setters. Implement rich domain methods (e.g., use `Order.Activate()` instead of `order.Status = "Active"`) to keep business rules secure.