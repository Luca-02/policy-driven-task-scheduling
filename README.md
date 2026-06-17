# policy-driven-task-scheduling

### TODO
- [ ] implementation of excidint indicator phi_prop
- [ ] implementation of geographical co-location:
  - [x] update node with location information label
  - [x] implementation of geographical group CRDs
  - [ ] update task-request CRDs and dataset metadata with requested geographical group
  - [ ] validation of dataset geographical group in dataset-service /validation
  - [ ] implementation of geographical co-location policy in task-request controller, calculate `geo*(t)` and using it to create the nodeAffinity in the related Job 