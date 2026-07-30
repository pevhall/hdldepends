library ieee;
use ieee.std_logic_1164.all;

-- A tiny package the counter depends on, so the example has a real
-- intra-project dependency edge (counter uses work.counter_pkg).
package counter_pkg is
  constant WIDTH : natural := 8;
end package counter_pkg;
