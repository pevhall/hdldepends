library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use std.textio.all;


entity del3 is
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

architecture sim of del3 is

  component up_down_counter is
    port (
      cntr_o : out std_logic_vector(7 downto 0);
      up_down_i : in std_logic;
      clk_i : in std_logic;
      rst_i : in std_logic;
    );
  end component;

  signal cntr : std_logic_vector(8-1 downto 0);

begin

 i_del : entity work.del211
 generic map (
   TEST     => TEST,
   sdf      => sdf,
   TESTsdf  => TESTsdf
 )
 port map (
   clk_i    => clk_i,
   en_i     => en_i,
   testa_i  => testa_i,
   testdb_i => testdb_i,
   tesdt_i  => tesdt_i,
   sdf_i    => sdf_i,
   tedast_i => tedast_i
 );

  i_up_down_cntr : entity work.up_down_counter
  port map (
    cntr_o    => cntr,
    up_down_i => '1',
    clk_i     => clk_i,
    rst_i     => '0'
  );

end architecture;

