## link

A link is an edge in a network, defined by the nodes it travels from and to. It may have associated geometry information. Links have three types of attributes:<br>  - Those that define the physical location of the link (e.g., `shape` `information`, `length`, `width`)<br>  - Those that define the link's directionality: `from_node`, `to_node`<br>  - Those that define properties in the direction of travel: capacity, free flow speed, number of lanes, permitted uses, grade, facility type

**Primary key:** `link_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `link_id` | any | required | Primary key - could be SharedStreets Reference ID |
| `name` | string |  | Optional. Street or Path Name |
| `from_node_id` | any | required | Required. Origin Node |
| `to_node_id` | any | required | Required. Destination Node |
| `directed` | boolean | required | Required. Whether the link is directed (travel only occurs from the from_node to the to_node) or undirected. |
| `geometry_id` | any |  | Optional. Foreign key (Link_Geometry table). |
| `geometry` | any |  | Optional. Link geometry, in well-known text (WKT) format. Optionally, other formats supported by geopandas (GeoJSON, PostGIS) may be used if specified in geometry_field_format in gmns.spec.json |
| `parent_link_id` | any |  | Optional. The parent of this link. For example,for a sidewalk, this is the adjacent road. |
| `dir_flag` | integer | enum=[1, -1, 0] | Optional. <br>1  shapepoints go from from_node to to_node;<br>-1 shapepoints go in the reverse direction;<br>0  link is undirected or no geometry information is provided. |
| `length` | number | min=0 | Optional. Length of the link in long_length units |
| `grade` | number | min=-100; max=100 | % grade, negative is downhill |
| `facility_type` | string |  | Facility type (e.g., freeway, arterial, etc.) |
| `capacity` | number | min=0 | Optional. Saturation capacity (passenger car equivalents / hr / lane) |
| `free_speed` | number | min=0; max=200 | Optional. Free flow speed, units defined by config file |
| `lanes` | integer | min=0 | Optional. Number of permanent lanes (not including turn pockets) in the direction of travel open to motor vehicles. It does not include bike lanes, shoulders or parking lanes. |
| `bike_facility` | string | enum=[unseparated bike lane, buffered bike lane, separated bike lane, counter-flow bike lane, paved shoulder, shared lane, … (+4 more)] | Optional. Type of bike facility along the link. |
| `ped_facility` | string | enum=[unknown, none, shoulder, sidewalk, offstreet_path, crosswalk] | Optional. Type of pedestrian accommodation along the link |
| `parking` | string | enum=[unknown, none, parallel, angle, other] | Optional. Type of parking along the link. |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `toll` | number |  | Optional.  Toll on the link, in currency units. |
| `jurisdiction` | string |  | Optional.  Owner/operator of the link. |
| `row_width` | number | min=0 | Optional. Width (short_length units) of the entire right-of-way (both directions). |

**Foreign keys:**

- `from_node_id` → `node`.`node_id`
- `to_node_id` → `node`.`node_id`
- `geometry_id` → `geometry`.`geometry_id`
- `parent_link_id` → `link`.`link_id`

## node

A list of vertices that locate points on a map. Typically, they will represent intersections, but may also represent other points, such as a transition between divided and undivided highway. Nodes are the endpoints of a link (as opposed to the other type of vertex, location, which is used to represent points along a link)

**Primary key:** `node_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `node_id` | any | required | Primary key |
| `name` | string |  |  |
| `x_coord` | number | required | Coordinate system specified in config file (longitude, UTM-easting etc.) |
| `y_coord` | number | required | Coordinate system specified in config file (latitude, UTM-northing etc.) |
| `z_coord` | number |  | Optional. Altitude in short_length units. |
| `node_type` | string |  | Optional. What it represents (intersection, transit station, park & ride). |
| `ctrl_type` | string | enum=[no_control, yield, stop, stop_2_way, stop_4_way, signal_with_RTOR, … (+1 more)] | Optional. Intersection control type. |
| `zone_id` | any |  | Optional. Could be a Transportation Analysis Zone (TAZ) or city, or census tract, or census block. |
| `parent_node_id` | any |  | Optional. Associated node. For example, if this node is a sidewalk, a parent_nodek_id could represent the intersection  it is associated with. |

**Foreign keys:**

- `zone_id` → `zone`.`zone_id`
- `parent_node_id` → `node`.`node_id`

## geometry

The geometry is an optional file that contains geometry information (shapepoints) for a line object. It is similar to Geometries in the SharedStreets reference system. The specification also allows for geometry information to be stored directly on the link table.

**Primary key:** `geometry_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `geometry_id` | any | required | Primary key - could be SharedStreets Geometry ID |
| `geometry` | any |  | Link geometry, in well-known text (WKT) format.  Optionally, other formats supported by geopandas (GeoJSON, PostGIS) may be used if specified in geometry_field_format in gmns.spec.json. |

## lane

The lane file allocates portions of the physical right-of-way that might be used for travel. It might be a travel lane, bike lane, or a parking lane. Lanes only are included in directed links; undirected links are assumed to have no lane controls or directionality. If a lane is added, dropped, or changes properties along the link, those changes are recorded on the `segment_link` table. Lanes are numbered sequentially, starting at either the centerline (two-way street) or the left shoulder (one-way street or divided highway with two centerlines).

**Primary key:** `lane_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `lane_id` | any | required | Primary key |
| `link_id` | any | required | Required. Foreign key to link table. |
| `lane_num` | integer | required; min=-10; max=10 | Required. e.g., -1, 1, 2 (use left-to-right numbering). By convention, the left-most through lane is 1. Left-turn lanes have negative numbers |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `r_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the right. |
| `l_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the left |
| `width` | number | min=0 | Optional. Width of the lane, short_length units. |

**Foreign keys:**

- `link_id` → `link`.`link_id`

## link_tod

Handles day-of-week and time-of-day restrictions on links

**Primary key:** `link_tod_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `link_tod_id` | any | required | Primary key |
| `link_id` | any | required | Required. Foreign key, link table |
| `timeday_id` | any |  | Conditionally required (either timeday_id or time_day). Foreign key to time_set_definitions. |
| `time_day` | string |  | Conditionally required (either timeday_id or time_day). XXXXXXXX_HHMM_HHMM, where XXXXXXXX is a bitmap of days of the week, Sunday-Saturday, Holiday. The HHMM are the start and end times. |
| `capacity` | number | min=0 | Optional.Saturation capacity (pce / hr / lane) |
| `free_speed` | number | min=0; max=200 | Optional. Free flow speed in long_distance units per hour |
| `lanes` | integer | min=0 | Optional. Number of permanent lanes (not including turn pockets) in the direction of travel open to motor vehicles. It does not include bike lanes, shoulders or parking lanes. |
| `bike_facility` | string | enum=[unseparated bike lane, buffered bike lane, separated bike lane, counter-flow bike lane, paved shoulder, shared lane, … (+4 more)] | Optional. Type of bike facility along the link. |
| `ped_facility` | string | enum=[unknown, none, shoulder, sidewalk, offstreet_path, crosswalk] | Optional. Type of pedestrian accommodation along the link |
| `parking` | string | enum=[unknown, none, parallel, angle, other] | Optional. Type of parking along the link. |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `toll` | number |  | toll in currency units. |

**Foreign keys:**

- `link_id` → `link`.`link_id`
- `timeday_id` → `time_set_definitions`.`timeday_id`

## location

A location is a vertex that is associated with a specific location along a link. Locations may be used to represent places where activities occur (e.g., driveways and bus stops). Its attributes are nearly the same as those for a node, except that the location includes an associated link and node, with location specified as distance along the link from the node.

**Primary key:** `loc_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `loc_id` | any | required | Primary key. Location ID. |
| `link_id` | any | required | Required. Road Link ID. Foreign Key from Road_Link. |
| `ref_node_id` | any | required | Required. The From node of the link. Foreign Key from Node. |
| `lr` | number | required; min=0 | Required. Linear Reference of the location, measured as distance in short_length units along the link from the reference node.  If link_geometry exists, it is used. Otherwise, link geometry is assumed to be a crow-fly distance from A node to B node. |
| `x_coord` | number |  | Optional. Either provided, or derived from Link, Ref_Node and LR. |
| `y_coord` | number |  | Optional. Either provided, or derived from Link, Ref_Node and LR. |
| `z_coord` | number |  | Optional. Altitude in short_length units. |
| `loc_type` | string |  | Optional. What it represents (driveway, bus stop, etc.) OpenStreetMap map feature names are recommended. |
| `zone_id` | any |  | Optional. Foreign Key, Associated zone |
| `gtfs_stop_id` | string |  | Optional. Foreign Key to GTFS data. For bus stops and transit station entrances, provides a link to the General Transit Feed Specification. |

**Foreign keys:**

- `link_id` → `link`.`link_id`
- `ref_node_id` → `node`.`node_id`

## movement

Describes how inbound and outbound links connect at an intersection.

**Primary key:** `mvmt_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `mvmt_id` | any | required | Primary key. |
| `node_id` | any | required | The node representing the junction. |
| `name` | string |  | Optional. |
| `ib_link_id` | any | required | Inbound link id. |
| `start_ib_lane` | integer |  | Innermost lane number the movement applies to at the inbound end. |
| `end_ib_lane` | integer |  | Outermost lane number the movement applies to at the inbound end. Blank indicates a movement with a single inbound lane. |
| `ob_link_id` | any | required | Outbound link id. |
| `start_ob_lane` | integer |  | Innermost lane number the movement applies to at the outbound end. |
| `end_ob_lane` | integer |  | Outermost lane number the movement applies to at the outbound end. Blank indicates a movement with a single outbound lane. |
| `type` | string | enum=[left, right, uturn, thru, merge, diverge] | Optional. Describes the type of movement (left, right, thru, etc.). |
| `penalty` | number |  | Turn penalty (seconds) |
| `capacity` | number |  | Saturation capacity in passenger car equivalents per hour. |
| `ctrl_type` | string | enum=[no_control, yield, stop, stop_2_way, stop_4_way, signal_with_RTOR, … (+1 more)] | Optional. |
| `mvmt_code` | string | pattern=`^[NSEW][EWB][RLT]\d?$` | Optional. Movement code (e.g., SBL).  Syntax is DDTN, where DD is the direction (e.g., SB, NB, EB, WB, NE, NW, SE, SW). T is the turning movement (e.g., R, L, T) and N is an optional turning movement number (e.g., distinguishing between bearing right and a sharp right at a 6-way intersection) |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `geometry` | any |  | Optional. Movement geometry, in well-known text (WKT) format. Optionally, other formats supported by geopandas (GeoJSON, PostGIS) may be used if specified in geometry_field_format in gmns.spec.json |

**Foreign keys:**

- `node_id` → `node`.`node_id`
- `ib_link_id` → `link`.`link_id`
- `ob_link_id` → `link`.`link_id`

## movement_tod

Handles day-of-week and time-of-day restrictions on movements.

**Primary key:** `mvmt_tod_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `mvmt_tod_id` | any | required | Primary key. |
| `mvmt_id` | any | required | The referenced movement. |
| `time_day` | string |  | Time of day in XXXXXXXX_HHMM_HHMM format, where XXXXXXXX is a bitmap of days of the week, Sunday-Saturday, Holiday. The HHMM are the start and end times. |
| `timeday_id` | any |  | Time of day set. Used if times-of-day are defined on the time_set_definitions table |
| `ib_link_id` | any | required | Inbound link id. |
| `start_ib_lane` | integer |  | Innermost lane number the movement applies to at the inbound end. |
| `end_ib_lane` | integer |  | Outermost lane number the movement applies to at the inbound end. Blank indicates a movement with a single inbound lane. |
| `ob_link_id` | any | required | Outbound link id. |
| `start_ob_lane` | integer |  | Innermost lane number the movement applies to at the outbound end. |
| `end_ob_lane` | integer |  | Outermost lane number the movement applies to at the outbound end. Blank indicates a movement with a single outbound lane. |
| `type` | string | enum=[left, right, uturn, thru, merge, diverge] | Optional. Describes the type of movement (left, right, thru, etc.). |
| `penalty` | number |  | Turn penalty (seconds) |
| `capacity` | number |  | Saturation capacity in passenger car equivalents per hour. |
| `ctrl_type` | string | enum=[no_control, yield, stop, stop_2_way, stop_4_way, signal_with_RTOR, … (+1 more)] | Optional. |
| `mvmt_code` | string | pattern=`^[NSEW][EWB][RLT]\d?$` | Optional. Movement code (e.g., SBL).  Syntax is DDTN, where DD is the direction (e.g., SB, NB, EB, WB, NE, NW, SE, SW). T is the turning movement (e.g., R, L, T) and N is an optional turning movement number (e.g., distinguishing between bearing right and a sharp right at a 6-way intersection) |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |

**Foreign keys:**

- `mvmt_id` → `movement`.`mvmt_id`
- `timeday_id` → `time_set_definitions`.`timeday_id`
- `ib_link_id` → `link`.`link_id`
- `ob_link_id` → `link`.`link_id`

## use_definition

The Use_Definition file defines the characteristics of each vehicle type or non-travel purpose (e.g., a shoulder or parking lane). A two-way left turn lane (TWLTL) is also a use.

**Primary key:** `use`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `use` | string | required | Primary key |
| `persons_per_vehicle` | number | required; min=0 | Required. |
| `pce` | number | required; min=0 | Required. Passenger car equivalent. |
| `special_conditions` | string |  | Optional. |
| `description` | string |  | Optional |

## use_group

Defines groupings of uses, to reduce the size of the allowed_uses lists in the other tables.

**Primary key:** `use_group`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `use_group` | string | required | Primary key. |
| `uses` | string | required | Comma-separated list of uses. |
| `description` | string |  | Optional. |

## time_set_definitions

The time_set_definitions file is an optional representation of time-of-day and day-of-week sets to enable time restrictions through `_tod` files.

**Primary key:** `timeday_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `timeday_id` | any | required | Primary key.Primary key, similar to `service_id` in GTFS. Unique name of the time of day. Preferable legible rather than a number. |
| `monday` | boolean | required | Required. Whether Mondays are included. |
| `tuesday` | boolean | required | Required. Whether Tuesdays are included. |
| `wednesday` | boolean | required | Required. Whether Wednesdays are included. |
| `thursday` | boolean | required | Required. Whether Thursdays are included. |
| `Friday` | boolean | required | Required. Whether Fridays are included. |
| `saturday` | boolean | required | Required. Whether Saturdays are included. |
| `sunday` | boolean | required | Required. Whether Sundays are included. |
| `holiday` | boolean | required | Required. Whether holidays are included. |
| `start_time` | time | required | Required. Start time in HH:MM format. |
| `end_time` | time | required | Required. End  time in HH:MM format. |

## segment

A portion of a link defined by `link_id`,`ref_node_id`, `start_lr`, and `end_lr`. Values in the segment will override they value specified in the link table. When one segment is fully contained within another, its value prevails.

**Primary key:** `segment_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `segment_id` | any | required | Primary key. |
| `link_id` | any | required | Required. Foreign key to road_links. The link that the segment is located on. |
| `ref_node_id` | any | required | Required. Foreign key to node where distance is 0. |
| `start_lr` | number | required; min=0 | Required. Distance from `ref_node_id` in short_length units. |
| `end_lr` | number | required; min=0 | Required. Distance from `ref_node_id`in short_length units. |
| `grade` | number | min=-100; max=100 | % grade, negative is downhill |
| `capacity` | number | min=0 | Optional. Saturation capacity (pce/hr/ln) |
| `free_speed` | number | min=0; max=200 | Optional. Free flow speed, units defined by config file |
| `lanes` | integer |  | Optional. Number of lanes in the direction of travel (must be consistent with link lanes + lanes added). |
| `l_lanes_added` | integer |  | Optional. # of lanes added on the left of the road link (negative indicates a lane drop). |
| `r_lanes_added` | integer |  | Optional. # of lanes added on the right of the road link (negative indicates a lane drop). |
| `bike_facility` | string | enum=[unseparated bike lane, buffered bike lane, separated bike lane, counter-flow bike lane, paved shoulder, shared lane, … (+4 more)] | Optional. Type of bike facility along the segment. |
| `ped_facility` | string | enum=[unknown, none, shoulder, sidewalk, offstreet_path, crosswalk] | Optional. Type of pedestrian accommodation along the segment |
| `parking` | string | enum=[unknown, none, parallel, angle, other] | Optional. Type of parking along the segment. |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `toll` | number |  | Optional.  Toll on the segment, in currency units. |
| `jurisdiction` | string |  | Optional. Optional.  Owner/operator of the segment. |
| `row_width` | number | min=0 | Optional. Width (short_length units) of the entire right-of-way (both directions). |

**Foreign keys:**

- `link_id` → `link`.`link_id`
- `ref_node_id` → `node`.`node_id`

## segment_lane

Defines added and dropped lanes, and changes to lane parameters. If a lane is added, it has no parent. If it is changed or dropped, the parent_lane_id field keys to the associated lane on the lane table.

**Primary key:** `segment_lane_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `segment_lane_id` | any | required | Primary key. |
| `segment_id` | any | required | Required. Foreign key to the associated segment. |
| `lane_num` | integer | required; min=-10; max=10 | Required. -1, 1, 2 (use left-to-right numbering). 0 signifies a lane that is dropped on the segment. |
| `parent_lane_id` | any |  | Optional. If a lane drops or changes characteristics on the segment, the lane_id for that lane. |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `r_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the right. |
| `l_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the left |
| `width` | number | min=0 | Optional. Width of the lane (short_length units) |

**Foreign keys:**

- `segment_id` → `segment`.`segment_id`

## signal_controller

The signal controller is associated with an intersection or a cluster of intersections.

**Primary key:** `controller_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `controller_id` | any | required | Primary key. |

## signal_coordination

Establishes coordination for several signal controllers, associated with a timing_plan.

**Primary key:** `coordination_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `coordination_id` | any | required | Primary key. |
| `timing_plan_id` | any | required | Required. Foreign key (Signal_timing_plan table). |
| `controller_id` | any | required | Required. Foreign key (signal_controller table). |
| `coord_contr_id` | any |  | Optional. For coordinated signals, the master signal controller for coordination. |
| `coord_phase` | integer | min=0; max=32 | Optional. For coordinated signals, the phase at which coordination starts (time 0). |
| `coord_ref_to` | string | enum=[begin_of_green, begin_of_yellow, begin_of_red] | Optional. For coordinated signals, the part of the phase where coordination starts: begin_of_green, begin_of_yellow, begin_of_red. |
| `offset` | number | min=0 | Optional. Offset in seconds. |

**Foreign keys:**

- `timing_plan_id` → `signal_timing_plan`.`timing_plan_id`
- `controller_id` → `signal_controller`.`controller_id`
- `coord_contr_id` → `signal_controller`.`controller_id`

## signal_phase_mvmt

Associates Movements and pedestrian Links (e.g., crosswalks) with signal phases. A signal phase may be associated with several movements. A Movement may also run on more than one phase.

**Primary key:** `signal_phase_mvmt_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `signal_phase_mvmt_id` | any | required | Primary key. |
| `timing_phase_id` | any | required | Associated entry in the timing phase table. |
| `mvmt_id` | any |  | Foreign key. Either Movement_ID (for phases used by vehicles), or Link_id (for phases used by pedestrians) is required. |
| `link_id` | any |  | Foreign key. Either Movement_ID (for phases used by vehicles), or Link_id (for phases used by pedestrians) is required. |
| `protection` | string | enum=[protected, permitted, rtor] | Optional. Indicates whether the phase is protected, permitted, or right turn on red. |

**Foreign keys:**

- `timing_phase_id` → `signal_timing_phase`.`timing_phase_id`
- `mvmt_id` → `movement`.`mvmt_id`
- `link_id` → `link`.`link_id`

## signal_timing_plan

For signalized nodes, establishes timing plans.

**Primary key:** `timing_plan_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `timing_plan_id` | any | required | Primary key. |
| `controller_id` | any | required | Required. Foreign key (signal_controller table). |
| `timeday_id` | any |  | Conditionally required (either timeday_id or time_day). Foreign key to time_set_definitions. |
| `time_day` | any |  | Conditionally required (either timeday_id or time_day). XXXXXXXX_HHMM_HHMM, where XXXXXXXX is a bitmap of days of the week, Sunday-Saturday, Holiday. The HHMM are the start and end times. |
| `cycle_length` | number | min=0; max=600 | Cycle length in seconds. |

**Foreign keys:**

- `controller_id` → `signal_controller`.`controller_id`
- `timeday_id` → `time_set_definitions`.`timeday_id`

## signal_timing_phase

For signalized nodes, provides signal timing and establishes phases that may run concurrently.

**Primary key:** `timing_phase_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `timing_phase_id` | any | required | Primary key. |
| `timing_plan_id` | any |  | Foreign key; connects to a timing_plan associated with a controller. |
| `signal_phase_num` | integer | required; min=0 | Signal phase number. Typically the NEMA phase number. |
| `min_green` | number | min=0 | The minimum green time in seconds for an actuated signal. Green time in seconds for a fixed time signal. |
| `max_green` | number | min=0 | Optional.The maximum green time in seconds for an actuated signal; the default is minimum green plus one extension |
| `extension` | number | min=0; max=120 | Optional. The number of seconds the green time is extended each time vehicles are detected. |
| `clearance` | number | min=0; max=120 | Yellow interval plus all red interval |
| `walk_time` | number | min=0; max=120 | If a pedestrian phase exists, the walk time in seconds |
| `ped_clearance` | number | min=0; max=120 | If a pedestrian phase exists, the flashing don't walk time. |
| `ring` | integer | required; min=0; max=12 | Required. Phases that may operate sequentially. With dual rings, two non-conflicting phases may operate at the same time |
| `barrier` | integer | required; min=0; max=12 | Required. Set of phases in both rings that must end at the same time |
| `position` | integer | required | Required. Position. |

**Foreign keys:**

- `timing_plan_id` → `signal_timing_plan`.`timing_plan_id`

## signal_detector

A signal detector is associated with a controller, a phase and a group of lanes.

**Primary key:** `detector_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `detector_id` | any | required | Primary key. |
| `controller_id` | any | required | Required. Foreign key to signal_controller table. |
| `signal_phase_num` | integer | required | Required. Number of the associated phase. |
| `link_id` | any | required | Foreign key. The link covered by the detector. |
| `start_lane` | integer | required | Left-most lane covered by the detector. |
| `end_lane` | integer |  | Right-most lane covered by the detector (blank if only one lane). |
| `ref_node_id` | any | required | The detector is on the approach to this node. |
| `det_zone_lr` | number | required | Required. Distance from from the stop bar to detector in short_length units. |
| `det_zone_front` | number |  | Optional. Linear reference of front of detection zone in short_length units. |
| `det_zone_back` | number |  | Optional. Linear reference of back of detection zone in short_length units. |
| `det_type` | string |  | Optional. Type of detector. |

**Foreign keys:**

- `controller_id` → `signal_controller`.`controller_id`
- `link_id` → `link`.`link_id`
- `ref_node_id` → `node`.`node_id`

## segment_tod

An optional file that handles day-of-week and time-of-day restrictions on segments. It is used for part-time changes in segment capacity and number of lanes.

**Primary key:** `segment_tod_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `segment_tod_id` | any | required | Primary key. |
| `segment_id` | any | required | Foreign key to segment table. |
| `timeday_id` | any |  | Conditionally required (either timeday_id or time_day). Foreign key to time_set_definitions. |
| `time_day` | string |  | Conditionally required (either timeday_id or time_day). XXXXXXXX_HHMM_HHMM, where XXXXXXXX is a bitmap of days of the week, Sunday-Saturday, Holiday. The HHMM are the start and end times. |
| `capacity` | number | min=0 | Optional. Saturation capacity  pce / hr / lane |
| `free_speed` | number | min=0; max=200 | Optional. Free flow speed in units defined by config file |
| `lanes` | integer |  | Optional. Number of lanes in the direction of travel (must be consistent with link lanes + lanes added). |
| `l_lanes_added` | integer |  | Optional. # of lanes added on the left of the road link (negative indicates a lane drop). |
| `r_lanes_added` | integer |  | Optional. # of lanes added on the right of the road link (negative indicates a lane drop). |
| `bike_facility` | string | enum=[unseparated bike lane, buffered bike lane, separated bike lane, counter-flow bike lane, paved shoulder, shared lane, … (+4 more)] | Optional. Type of bike facility along the segment. |
| `ped_facility` | string | enum=[unknown, none, shoulder, sidewalk, offstreet_path, crosswalk] | Optional. Type of pedestrian accommodation along the segment |
| `parking` | string | enum=[unknown, none, parallel, angle, other] | Optional. Type of parking along the segment. |
| `toll` | number |  | Optional. Toll in currency units |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |

**Foreign keys:**

- `segment_id` → `segment`.`segment_id`
- `timeday_id` → `time_set_definitions`.`timeday_id`

## lane_tod

An optional file that handles day-of-week and time-of-day restrictions on lanes that traverse entire links.

**Primary key:** `lane_tod_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `lane_tod_id` | any | required | Primary key. |
| `lane_id` | any | required | Required. Foreign key to `lane` |
| `timeday_id` | any |  | Conditionally required (either timeday_id or time_day). Foreign key to time_set_definitions. |
| `time_day` | string |  | Conditionally required (either timeday_id or time_day). XXXXXXXX_HHMM_HHMM, where XXXXXXXX is a bitmap of days of the week, Sunday-Saturday, Holiday. The HHMM are the start and end times. |
| `lane_num` | integer | required; min=-10; max=10 | Required. Lane number identified as offset to the right from the centerline. i.e. -1, 1, 2 (use left-to-rightnumbering). |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `r_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the right. |
| `l_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the left |
| `width` | number | min=0 | Optional. Width of the lane, short_length units. |

**Foreign keys:**

- `lane_id` → `lane`.`lane_id`
- `timeday_id` → `time_set_definitions`.`timeday_id`

## segment_lane_tod

An optional file that handles day-of-week and time-of-day restrictions on lanes within segments of links.

**Primary key:** `segment_lane_tod_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `segment_lane_tod_id` | any | required | Primary key. |
| `segment_lane_id` | any | required | Required. Foreign key, segment_lane table |
| `timeday_id` | any |  | Conditionally required (either timeday_id or time_day). Foreign key to time_set_definitions. |
| `time_day` | string |  | Conditionally required (either timeday_id or time_day). XXXXXXXX_HHMM_HHMM, where XXXXXXXX is a bitmap of days of the week, Sunday-Saturday, Holiday. The HHMM are the start and end times. |
| `lane_num` | integer | required; min=-10; max=10 | Required. Lane number identified as offset to the right from the centerline. i.e. -1, 1, 2 (use left-to-rightnumbering). |
| `allowed_uses` | string |  | Optional. Set of allowed uses that should appear in either the use_definition or use_group tables; comma-separated. |
| `r_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the right. |
| `l_barrier` | string | enum=[none, regulatory, physical] | Optional. Whether a barrier exists to prevent vehicles from changing lanes to the left |
| `width` | number | min=0 | Optional. Width of the lane, short_length units. |

**Foreign keys:**

- `segment_lane_id` → `segment_lane`.`segment_lane_id`
- `timeday_id` → `time_set_definitions`.`timeday_id`

## zone

Locates zones (travel analysis zones, parcels) on a map. Zones are represented as polygons in geographic information systems.

**Primary key:** `zone_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `zone_id` | any | required | Primary key. |
| `name` | string |  | Optional. |
| `boundary` | any |  | Optional. The polygon geometry of the zone, as well-known text. |
| `super_zone` | string |  | Optional. If there is a hierarchy of zones (e.g., parcels and TAZs), indicates the zone of next higher level. |

**Foreign keys:**

- `super_zone` → `zone`.`zone_id`

## config

Configuration information for the dataset (units, coordinate systems, etc.).

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `dataset_name` | any |  | Name used to describe this GMNS network |
| `short_length` | any |  | Length unit used for lane/ROW widths and linear references for segments, locations, etc. along links |
| `long_length` | any |  | Length unit used for link lengths |
| `speed` | any |  | Units for speed. Usually long_length units per hour |
| `crs` | any |  | Coordinate system used for geometry data in this dataset. Preferably a string that can be accepted by pyproj (e.g., EPSG code or proj string) |
| `geometry_field_format` | any |  | The format used for geometry fields in the dataset. For example, `WKT` for files stored as plaintext |
| `currency` | any |  | Currency used in toll fields |
| `version_number` | number |  | The version of the GMNS spec to which this dataset conforms |
| `id_type` | string | enum=[string, integer] | The type of primary key IDs for interopability (node_id, zone_id, etc.). May be enforced by user, database schema, or downstream software. Must be either string or integer. |

## curb_seg

Provides a separate segment object for curbside regulations, which may change at different locations than segment-level changes to the travel lanes.

**Primary key:** `curb_seg_id`

| Field | Type | Constraints | Description |
| --- | --- | --- | --- |
| `curb_seg_id` | any | required | Primary key. |
| `link_id` | any | required | Required. Foreign key to road_links. The link that the segment is located on. |
| `ref_node_id` | any | required | Required. Foreign key to node where distance is 0. |
| `start_lr` | number | required; min=0 | Required. Distance from `ref_node_id` in short_length units. |
| `end_lr` | number | required; min=0 | Required. Distance from `ref_node_id`in short_length units. |
| `regulation` | string |  | Optional. Regulation on this curb segment. |
| `width` | number | min=0 | Optional. Width (short_length units) of the curb segment. |

**Foreign keys:**

- `link_id` → `link`.`link_id`
- `ref_node_id` → `node`.`node_id`
