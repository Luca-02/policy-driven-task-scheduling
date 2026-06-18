# policy-driven-task-scheduling

### TODO
- [ ] implementation of excidint indicator phi_prop
- [ ] implementation of geographical co-location:
  - [x] update node with location information label
  - [x] implementation of geographical group CRDs
  - [x] update task-request CRDs and dataset metadata with requested geographical group
  - [x] validation of dataset geographical group with dataset-service /validation
  - [ ] implementation of geographical co-location policy in task-request controller, calculate `geo*(t)` and using it to create the nodeAffinity in the related Job 