extern crate generational_arena;

use self::generational_arena::{Arena, Index};
use std::collections::HashSet;
use std::cell::*;

#[derive(Copy, Clone)]
pub enum Value<'a> {
    Graph(GraphPtr<'a>),
    // Other types later
}

struct Graph<'a> {
    parameters: Vec<ANFNodePtr<'a>>,
    return_: Option<ANFNodePtr<'a>>,
    //debug:
    //flags:
    //transforms: HashMap<String, GraphPtr>,
}

#[derive(Copy, Clone)]
pub struct GraphPtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>,
}

impl<'a> GraphPtr<'a> {
    fn get(&self) -> Ref<Graph<'a>> {
        self.manager.graphs.get(self.p).unwrap().borrow()
    }

    fn get_mut(&mut self) -> RefMut<Graph<'a>> {
        self.manager.graphs.get(self.p).unwrap().borrow_mut()
    }

    pub fn get_output(&'a self) -> Option<ANFNodePtr<'a>> {
        self.get().return_
    }

    pub fn set_output(&'a mut self, out: ANFNodePtr<'a>) -> () {
        self.get_mut().return_ = Some(out);
    }
}

#[derive(Clone)]
enum ANFNodeType<'a> {
    Apply(Vec<ANFNodePtr<'a>>),
    Parameter,
    Constant(Value<'a>),
}

struct ANFNode<'a> {
    node: ANFNodeType<'a>,
    graph: Option<GraphPtr<'a>>,
}

pub struct ANFNodeInputIter<'a> {
    vals: Vec<ANFNodePtr<'a>>,
    p: usize,
}

impl<'a> ANFNodeInputIter<'a> {
    fn new(node: Ref<'a, ANFNode<'a>>) -> Self {
        ANFNodeInputIter {
            vals: match &node.node {
                ANFNodeType::Apply(inps) => inps.clone(),
                _ => Vec::new(),
            },
            p: 0,
        }
    }
}

impl<'a> Iterator for ANFNodeInputIter<'a> {
    type Item = ANFNodePtr<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        let elem = self.vals.get(self.p);
        self.p += 1;
        if let Some(v) = elem {
            Some(*v)
        } else {
            None
        }
    }
}

#[derive(Copy, Clone)]
pub struct ANFNodePtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>,
}

impl<'a> ANFNodePtr<'a> {
    fn get(&self) -> Ref<ANFNode<'a>> {
        self.manager.all_nodes.get(self.p).unwrap().borrow()
    }

    pub fn incoming(&'a self) -> ANFNodeInputIter<'a> {
        ANFNodeInputIter::new(self.get())
    }

    pub fn value(&'a self) -> Option<Value<'a>> {
        let n = &self.get().node;
        match n {
            ANFNodeType::Constant(v) => Some(*v),
            _ => None,
        }
    }

    // Maybe value matching later, if needed
    pub fn is_apply(&self) -> bool {
        matches!(&self.get().node, ANFNodeType::Apply(_))
    }

    pub fn is_parameter(&self) -> bool {
        matches!(&self.get().node, ANFNodeType::Parameter)
    }

    // Some way to check for type later, if needed
    pub fn is_constant(&self) -> bool {
        matches!(&self.get().node, ANFNodeType::Constant(_))
    }

    pub fn is_constant_graph(&self) -> bool {
        matches!(&self.get().node, ANFNodeType::Constant(Value::Graph(_)))
    }
}

pub struct GraphManager<'a> {
    roots: HashSet<ANFNodePtr<'a>>,
    all_nodes: Arena<RefCell<ANFNode<'a>>>,
    graphs: Arena<RefCell<Graph<'a>>>,
}

impl<'a> GraphManager<'a> {
    pub fn new() -> Self {
        GraphManager {
            roots: HashSet::<ANFNodePtr<'a>>::new(),
            all_nodes: Arena::new(),
            graphs: Arena::new(),
        }
    }

    pub fn new_graph(&'a mut self) -> GraphPtr<'a> {
        let p = Vec::new();
        let g = self.graphs.insert(RefCell::new(Graph {
            parameters: p,
            return_: None,
        }));
        let s = &*self;
        GraphPtr { p: g, manager: s }
    }

    pub fn alloc_apply(&'a mut self, params: Vec<ANFNodePtr<'a>>) -> ANFNodePtr<'a> {
        let n = ANFNodeType::Apply(params);
        let a = self.all_nodes.insert(RefCell::new(ANFNode {
            node: n,
            graph: None,
        }));
        let s = &*self;
        ANFNodePtr { p: a, manager: s }
    }
}
