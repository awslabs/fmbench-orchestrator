# FMBench Orchestrator Refactoring Plan

## Overview

This document outlines the plan to refactor the FMBench Orchestrator into a more maintainable, scalable, and robust system using enhanced Pydantic validation and modern Python best practices.

## Current Architecture

The current system consists of:
- Configuration management using basic Pydantic models
- Instance orchestration through direct AWS interactions
- Synchronous and asynchronous benchmark execution
- Basic result collection and storage

## Target Architecture

### 1. Domain Models

Enhanced Pydantic models with strict validation and clear domain boundaries:

```python
class BenchmarkConfig(BaseModel):
    model_id: str
    batch_sizes: List[int]
    sequence_lengths: List[int]
    num_iterations: int
    timeout_seconds: int

    @field_validator("batch_sizes")
    def validate_batch_sizes(cls, v):
        if not v or any(size <= 0 for size in v):
            raise ValueError("Batch sizes must be positive integers")
        return v

class InstanceSpec(BaseModel):
    instance_type: str
    region: str
    ami_id: str
    storage_config: StorageConfig
    network_config: Optional[NetworkConfig]
    
    @field_validator("instance_type")
    def validate_instance_type(cls, v):
        valid_types = ["g4dn.xlarge", "p3.2xlarge", "c5.2xlarge"]
        if v not in valid_types:
            raise ValueError(f"Instance type {v} not supported")
        return v

class BenchmarkResult(BaseModel):
    model_id: str
    instance_id: str
    metrics: Dict[str, float]
    timestamps: Dict[str, datetime]
    status: Literal["success", "failure", "timeout"]
```

### 2. Service Layer

Clear service boundaries with dependency injection:

```python
class InstanceService(ABC):
    @abstractmethod
    async def provision(self, spec: InstanceSpec) -> str:
        """Provision an instance and return its ID"""
        pass

    @abstractmethod
    async def terminate(self, instance_id: str) -> None:
        """Terminate an instance"""
        pass

class BenchmarkService(ABC):
    @abstractmethod
    async def run_benchmark(
        self, 
        instance_id: str, 
        config: BenchmarkConfig
    ) -> BenchmarkResult:
        """Run benchmark and return results"""
        pass
```

### 3. Infrastructure Layer

Abstracted infrastructure interactions:

```python
class AWSInstanceService(InstanceService):
    def __init__(self, ec2_client: EC2Client):
        self.ec2_client = ec2_client

    async def provision(self, spec: InstanceSpec) -> str:
        # Implementation using AWS SDK
        pass

class S3StorageService(StorageService):
    def __init__(self, s3_client: S3Client):
        self.s3_client = s3_client

    async def store_result(self, result: BenchmarkResult) -> None:
        # Implementation using AWS SDK
        pass
```

## Migration Plan

### Phase 1: Domain Model Enhancement (Week 1-2)

1. Create new Pydantic models in `fmbench_orchestrator/models/`
   - benchmark.py
   - instance.py
   - config.py
   - results.py

2. Add comprehensive validation rules
   - Instance type validation
   - Resource limits
   - Configuration validation

3. Create migration utilities to convert between old and new models

### Phase 2: Service Layer Implementation (Week 3-4)

1. Create service interfaces in `fmbench_orchestrator/services/`
   - instance_service.py
   - benchmark_service.py
   - storage_service.py

2. Implement AWS-specific services
   - aws_instance_service.py
   - aws_storage_service.py

3. Add unit tests for services

### Phase 3: Infrastructure Abstraction (Week 5-6)

1. Create infrastructure interfaces
   - Create EC2Client abstraction
   - Create S3Client abstraction
   - Add mock implementations for testing

2. Implement concrete AWS implementations
   - Move AWS-specific code to infrastructure layer
   - Add retry mechanisms
   - Add proper error handling

### Phase 4: Orchestration Layer (Week 7-8)

1. Create new orchestrator classes
   - BenchmarkOrchestrator
   - ResultHandler
   - ConfigurationManager

2. Implement new CLI interface
   - Use dependency injection
   - Add proper logging
   - Add telemetry

### Phase 5: Testing & Documentation (Week 9-10)

1. Comprehensive testing
   - Unit tests for all components
   - Integration tests for AWS interactions
   - End-to-end tests for full workflows

2. Documentation
   - API documentation
   - Usage examples
   - Configuration guide

## Directory Structure

```
fmbench_orchestrator/
├── models/
│   ├── __init__.py
│   ├── benchmark.py
│   ├── instance.py
│   ├── config.py
│   └── results.py
├── services/
│   ├── __init__.py
│   ├── instance_service.py
│   ├── benchmark_service.py
│   └── storage_service.py
├── infrastructure/
│   ├── __init__.py
│   ├── aws/
│   │   ├── __init__.py
│   │   ├── ec2_client.py
│   │   └── s3_client.py
│   └── interfaces/
│       ├── __init__.py
│       ├── compute.py
│       └── storage.py
├── core/
│   ├── __init__.py
│   ├── orchestrator.py
│   ├── result_handler.py
│   └── config_manager.py
└── cli.py
```

## Benefits

1. **Enhanced Validation**
   - Stricter type checking
   - Better error messages
   - Runtime validation of configurations

2. **Improved Maintainability**
   - Clear separation of concerns
   - Dependency injection
   - Testable components

3. **Better Error Handling**
   - Specific error types
   - Proper error propagation
   - Better recovery mechanisms

4. **Enhanced Testability**
   - Mockable interfaces
   - Isolated components
   - Clear boundaries

5. **Future-Proofing**
   - Easy to add new cloud providers
   - Support for different benchmark types
   - Extensible architecture

## Risks and Mitigations

1. **Risk**: Breaking changes in public API
   - **Mitigation**: Version new API, maintain compatibility layer

2. **Risk**: Performance overhead from additional validation
   - **Mitigation**: Profile and optimize critical paths

3. **Risk**: Migration complexity
   - **Mitigation**: Phased approach, thorough testing

## Success Metrics

1. Code coverage > 90%
2. Reduced error rates in production
3. Faster onboarding time for new developers
4. Reduced time to implement new features

## Next Steps

1. Review and approve architecture
2. Set up new project structure
3. Begin Phase 1 implementation
4. Schedule regular reviews