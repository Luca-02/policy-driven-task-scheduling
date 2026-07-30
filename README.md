# policy-driven-task-scheduling

### TODO
- [x] implement iss : T -> I
- [x] implement ctx : D -> 2^X
- [x] implement X_conf, pair of contexts in conflict
- [ ] assume (ctx(d) x ctx(d)) intersection X_conf = empty, for each d in D
- [x] implement auth : I -> 2^X
- [x] assume (auth(i) x auth(i)) intersection X_conf = empty, for each i in I
- [x] implement c_auth: for each d in req(t), ctx(d) subset of auth(iss(t))
- [x] calculate trace of a task ctx*(t) = union of ctx(d) for each d in req(t) 
- [ ] implement nodes memory Lambda : N -> 2^X
- [ ] implement nodes memory update such as: f(t) != null => Lambda(f(t)) = Lambda(f(t)) union ctx*(t)
- [ ] implement c_wall: (auth(iss(t)) x Lambda(n)) intersection X_conf = empty
- [ ] implement sanification of nodes 