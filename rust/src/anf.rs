extern crate generational_arena;

use self::generational_arena::Arena;
use self::generational_arena::Index;
use std::collections::HashSet;
use std::collections::HashMap;

struct Graph<'a> {
    parameters: Vec<ANFNodePtr<'a>>,
    return_: Option<ANFNodePtr<'a>>,
    //debug:
    //transforms: HashMap<String, GraphPtr>,
}

#[derive(Copy, Clone)]
pub struct GraphPtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>
}

impl<'a> GraphPtr<'a> {
    pub fn get_output(& self) -> Option<ANFNodePtr<'a>> {
        let ret = self.manager.graphs[self.p].return_;
        ret
    }
}

enum GraphValueType {
}

enum ANFNodeType<'a> {
    Apply(Vec<ANFNodePtr<'a>>),
    Parameter,
    Constant(GraphValueType),
}

struct ANFNode<'a> {
    node: ANFNodeType<'a>,
    graph: Option<GraphPtr<'a>>
}

#[derive(Copy, Clone)]
pub struct ANFNodePtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>
}

pub struct GraphManager<'a> {
    roots: HashSet<ANFNodePtr<'a>>,
    all_nodes: Arena<ANFNode<'a>>,
    graphs: Arena<Graph<'a>>,
}

impl<'a> GraphManager<'a> {
    pub fn new() -> GraphManager<'a> {
        GraphManager { roots: HashSet::<ANFNodePtr<'a>>::new(),
                       all_nodes: Arena::new(),
                       graphs: Arena::new() }
    }

    pub fn new_graph(&mut self) -> GraphPtr {
        let p = Vec::new();
        let g = self.graphs.insert(Graph { parameters: p, return_: None });
        let s = &*self;
        GraphPtr { p: g, manager: s }
    }

    pub fn alloc_apply(&mut self, params: Vec<ANFNodePtr<'a>>) -> ANFNodePtr {
        let n = ANFNodeType::Apply(params);
        let a = self.all_nodes.insert(ANFNode { node: n, graph: None });
        let s = &*self;
        ANFNodePtr { p: a, manager: s }
    }
}
