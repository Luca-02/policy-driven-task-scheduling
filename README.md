# policy-driven-task-scheduling

- [ ] in the task-request-controller, update the dataset-service client using the /dataset/query endpoint, avoiding fetching one by one all the datasets. This is a performance improvement, as the dataset-service can filter datasets by name and return only the requested ones. Also rename it dataset_client with a class DatasrtClient, its not a service.