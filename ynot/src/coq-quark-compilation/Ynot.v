Require Import Qcanon.
Require Export Axioms.
Require Export Util.
Require Export PermModel.
Require Export Heap.
Require Export Hprop.
Require Export ST.
Require Export STsep.
Require Export Separation.
Require Export Sep.
Require Export Hprop2.
Require Export Case.

(* for some reason, this does not create a conflict here, but does elsewhere *)
Notation "p --> v" := (hprop_cell p v (0%Qc)) (at level 38, no associativity) : hprop_scope.
Notation "p !! P" := (SepRead p P ([0%Qc])) (no associativity, at level 75) : stsep_scope.
