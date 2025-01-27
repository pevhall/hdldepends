library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use std.textio.all;


entity del211 is
  generic (
    TEST : integer;
    sdf : in  std_logic_vector(32-1 downto 0);
    TESTsdf : integer
  );
  port (
    clk_i : in  std_logic;
    en_i : in  std_logic; --(((
    testa_i : in  std_logic;
    testdb_i : in  std_logic;
    tesdt_i : in  std_logic;
    sdf_i : in  std_logic_vector(32-1 downto 0);
    tedast_i : out  std_logic

  );
end entity;

architecture sim of del211 is

begin

--  i_del : entity work.del211
--  generic map (
--    TEST     => TEST,
--    sdf      => sdf,
--    TESTsdf  => TESTsdf
--  )
--  port map (
--    clk_i    => clk_i,
--    en_i     => en_i,
--    testa_i  => testa_i,
--    testdb_i => testdb_i,
--    tesdt_i  => tesdt_i,
--    sdf_i    => sdf_i,
--    tedast_i => tedast_i
--  );


end architecture;

