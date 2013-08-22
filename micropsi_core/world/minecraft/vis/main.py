from __future__ import division
from shutil import move

from pyglet.gl import *
from pyglet.window import key
import sys
import math
import time
import os

from micropsi_core.world.minecraft.vis.structs import block_names, load_textures, has_sides

SECTOR_SIZE = 16

WINDOW = None


if sys.version_info[0] >= 3:
    xrange = range

def cube_vertices(x, y, z, n):
    return [
        x-n,y+n,z-n, x-n,y+n,z+n, x+n,y+n,z+n, x+n,y+n,z-n, # top
        x-n,y-n,z-n, x+n,y-n,z-n, x+n,y-n,z+n, x-n,y-n,z+n, # bottom
        x-n,y-n,z-n, x-n,y-n,z+n, x-n,y+n,z+n, x-n,y+n,z-n, # left
        x+n,y-n,z+n, x+n,y-n,z-n, x+n,y+n,z-n, x+n,y+n,z+n, # right
        x-n,y-n,z+n, x+n,y-n,z+n, x+n,y+n,z+n, x-n,y+n,z+n, # front
        x+n,y-n,z-n, x-n,y-n,z-n, x-n,y+n,z-n, x+n,y+n,z-n, # back
    ]

def cube_vertices_top(x, y, z, n):
    return [
        x-n,y+n,z-n, x-n,y+n,z+n, x+n,y+n,z+n, x+n,y+n,z-n, # top
        #x-n,y-n,z-n, x+n,y-n,z-n, x+n,y-n,z+n, x-n,y-n,z+n, # bottom
        #x-n,y-n,z-n, x-n,y-n,z+n, x-n,y+n,z+n, x-n,y+n,z-n, # left
        #x+n,y-n,z+n, x+n,y-n,z-n, x+n,y+n,z-n, x+n,y+n,z+n, # right
        #x-n,y-n,z+n, x+n,y-n,z+n, x+n,y+n,z+n, x-n,y+n,z+n, # front
        #x+n,y-n,z-n, x-n,y-n,z-n, x-n,y+n,z-n, x+n,y+n,z-n, # back
    ]

def cube_vertices_sides(x, y, z, n):
    return [
        #x-n,y+n,z-n, x-n,y+n,z+n, x+n,y+n,z+n, x+n,y+n,z-n, # top
        #x-n,y-n,z-n, x+n,y-n,z-n, x+n,y-n,z+n, x-n,y-n,z+n, # bottom
        x-n,y-n,z-n, x-n,y-n,z+n, x-n,y+n,z+n, x-n,y+n,z-n, # left
        x+n,y-n,z+n, x+n,y-n,z-n, x+n,y+n,z-n, x+n,y+n,z+n, # right
        x-n,y-n,z+n, x+n,y-n,z+n, x+n,y+n,z+n, x-n,y+n,z+n, # front
        x+n,y-n,z-n, x-n,y-n,z-n, x-n,y+n,z-n, x+n,y+n,z-n, # back
    ]

def tex_coord(x, y, n=1):
    m = 1.0 / n
    dx = x * m
    dy = y * m
    return dx, dy, dx + m, dy, dx + m, dy + m, dx, dy + m

def tex_coords(top, bottom, side):
    top = tex_coord(*top)
    bottom = tex_coord(*bottom)
    side = tex_coord(*side)
    result = []
    result.extend(top)
    result.extend(bottom)
    result.extend(side * 4)
    return result

def tex_coords_top(top, bottom, side):
    top = tex_coord(*top)
    bottom = tex_coord(*bottom)
    side = tex_coord(*side)
    result = []
    result.extend(top)
    #result.extend(bottom)
    #result.extend(side * 4)
    return result

def tex_coords_sides(top, bottom, side):
    top = tex_coord(*top)
    bottom = tex_coord(*bottom)
    side = tex_coord(*side)
    result = []
    #result.extend(top)
    #result.extend(bottom)
    result.extend(side * 4)
    return result

GRASS = tex_coords((1, 0), (0, 1), (0, 0))# (row, line)
SAND = tex_coords((1, 1), (1, 1), (1, 1))
BRICK = tex_coords((2, 0), (2, 0), (2, 0))
GOLDORE = tex_coords((0, 0), (0, 0), (0, 0))
STONE = tex_coords((2, 1), (2, 1), (2, 1))
HUMAN = tex_coords((3, 2), (3, 2), (3, 1))

FACES = [
    ( 0, 1, 0),
    #( 0,-1, 0),
    #(-1, 0, 0),
    #( 1, 0, 0),
    #( 0, 0, 1),
    #( 0, 0,-1),
]

class TextureGroup(pyglet.graphics.Group):
    def __init__(self, path):
        super(TextureGroup, self).__init__()
        self.texture = pyglet.image.load(path).get_texture()
    def set_state(self):
        glEnable(self.texture.target)
        glBindTexture(self.texture.target, self.texture.id)
    def unset_state(self):
        glDisable(self.texture.target)

def normalize(position):
    x, y, z = position
    x, y, z = (int(round(x)), int(round(y)), int(round(z)))
    return (x, y, z)

def sectorize(position):
    x, y, z = normalize(position)
    x, y, z = x // SECTOR_SIZE, y // SECTOR_SIZE, z // SECTOR_SIZE
    return (x, 0, z)

class Model(object):
    def __init__(self, client):
        self.batch = pyglet.graphics.Batch()
        print(os.getcwd())
        self.group = TextureGroup('micropsi_core/world/minecraft/vis/texture.png')
        load_textures(self)
        self.world = {}
        self.type = {}
        self.shown = {}
        self._shown = {}
        self.sectors = {}
        self.queue = []
        self.client = client
        self.initialize()
        self.last_known_botblock = (0,0,0)
    def initialize(self):
        n = 16
        s = 1
        y = 0

        x_chunk = self.client.position['x'] // 16
        z_chunk = self.client.position['z'] // 16

        bot_block = [self.client.position['x'], self.client.position['y'], self.client.position['z']]
        current_column = self.client.world.columns[(x_chunk, z_chunk)]
        current_section = current_column.chunks[int((bot_block[1] + y % 16) // 16)]

        for x in xrange(0, n):
            for y in xrange(0, n):
                for z in xrange(0, n):
                    if current_section != None:
                        current_block = current_column.chunks[int((bot_block[1] + y - 10 // 2) // 16)]['block_data'].get(x, int((bot_block[1] + y - 10 // 2) % 16), z)
                        if (current_block in (1, 2, 3, 4, 5, 7, 10, 11, 12, 13, 14, 15, 16, 19, 21, 22, 24, 25, 35, 41, 42, 43, 45, 46, 47, 48, 49, 52, 56, 57, 73, 74, 80, 82, 84, 87, 88, 89, 97, 98, 103, 110, 112, 121, 123, 124, 125, 125, 129, 133, 137, 152, 153, 155, 159, 172, 173)):
                            #print(current_block)
                            #print(self.block_names[str(current_block)])
                            self.init_block((x, y, z), GOLDORE, block_names[str(current_block)])

    def reload(self):
        n = 16
        s = 1
        y = 0

        x_chunk = self.client.position['x'] // 16
        z_chunk = self.client.position['z'] // 16

        bot_block = [self.client.position['x'], self.client.position['y'], self.client.position['z']]
        current_column = self.client.world.columns[(x_chunk, z_chunk)]
        current_section = current_column.chunks[int((bot_block[1] + y % 16) // 16)]

        for x in xrange(0, n):
            for y in xrange(0, n):
                for z in xrange(0, n):
                    if current_section != None:
                        current_block = current_column.chunks[int((bot_block[1] + y - 10 // 2) // 16)][
                            'block_data'].get(x, int((bot_block[1] + y - 10 // 2) % 16), z)
                        if current_block == 14:
                           #self.add_block((x, y, z), GOLDORE)
                            pass
                        elif current_block == 3:
                           #self.add_block((x, y, z), SAND)
                            pass
                        elif current_block == 1:
                           #self.add_block((x, y, z), STONE)
                            pass
                        elif current_block == 13:
                           #self.add_block((x, y, z), STONE)
                            pass
                        elif current_block == 2:
                           #self.add_block((x, y, z), GRASS)
                            pass
                        if [int(self.client.position['x'] % 16), int((bot_block[1] + y - 10 // 2) // 16), int(self.client.position['z'] % 16)] == [x,y,z]:
                            print("BotBlock @ x %s y %s z %s" % (x,y,z))
                            self.remove_block(self.last_known_botblock)
                            self.add_block((x, y+1, z), HUMAN, "oreGold" )
                            self.last_known_botblock = (x, y+1, z)
                            
    def hit_test(self, position, vector, max_distance=8):
        m = 8
        x, y, z = position
        dx, dy, dz = vector
        previous = None
        for _ in xrange(max_distance * m):
            key = normalize((x, y, z))
            if key != previous and key in self.world:
                return key, previous
            previous = key
            x, y, z = x + dx / m, y + dy / m, z + dz / m
        return None, None
    def exposed(self, position):
        x, y, z = position
        for dx, dy, dz in FACES:
            if (x + dx, y + dy, z + dz) not in self.world:
                return True
        return False
    def init_block(self, position, texture, type):
        self.add_block(position, texture, type, False)
    def own_init_block(self, position, texture):
        self.own_add_block(position, texture, False)
    def own_add_block(self, position, texture, sync=True):
        if position in self.world:
            self.remove_block(position, sync)
        self.world[position] = texture
        self.sectors.setdefault(sectorize(position), []).append(position)
        if sync:
            if self.exposed(position):
                self.show_own_block(position)
            self.check_neighbors(position)
    def add_block(self, position, texture, type, sync=True):
        if position in self.world:
            self.remove_block(position, sync)
        self.type[position] = type
        self.world[position] = texture
        self.sectors.setdefault(sectorize(position), []).append(position)
        if sync:
            if self.exposed(position):
                self.show_block(position)
            self.check_neighbors(position)
    def remove_block(self, position, sync=True):
        del self.world[position]
        self.sectors[sectorize(position)].remove(position)
        if sync:
            if position in self.shown:
                self.hide_block(position)
            self.check_neighbors(position)
    def check_neighbors(self, position):
        x, y, z = position
        for dx, dy, dz in FACES:
            key = (x + dx, y + dy, z + dz)
            if key not in self.world:
                continue
            if self.exposed(key):
                if key not in self.shown:
                    self.show_own_block(key)
            else:
                if key in self.shown:
                    self.hide_block(key)
    def show_blocks(self):
        for position in self.world:
            if position not in self.shown and self.exposed(position):
                self.show_own_block(position)
    def show_block(self, position, immediate=True):
        texture = self.world[position]
        self.shown[position] = texture
        if immediate:
            self._show_block(position, texture)
        else:
            self.enqueue(self._show_block, position, texture)
    def show_own_block(self, position, immediate=True):
        texture = self.world[position]
        self.shown[position] = texture
        if immediate:
            self._show_own_block(position, texture)
        else:
            self.enqueue(self._show_own_block, position, texture)
    def _show_block(self, position, texture):
        x, y, z = position

        if self.type[position] in has_sides:
            # only show exposed faces
            index = 0
            count = 4
            vertex_data = cube_vertices_top(x, y, z, 0.5)
            texture_data = list(tex_coords_top((0, 0), (0, 0), (0, 0)))
            self._shown[position] = self.batch.add(count, GL_QUADS, self.texturepack[self.type[position]],
                    ('v3f/static', vertex_data),
                    ('t2f/static', texture_data))

            vertex_data = cube_vertices_sides(x, y, z, 0.5)
            texture_data = list(tex_coords_sides((0, 0), (0, 0), (0, 0)))
            self._shown[position] = self.batch.add(16, GL_QUADS, self.side_files[self.type[position]],
                ('v3f/static', vertex_data),
                ('t2f/static', texture_data))

        else:
            # only show exposed faces
            index = 0
            count = 24
            vertex_data = cube_vertices(x, y, z, 0.5)
            texture_data = list(tex_coords((0, 0), (0, 0), (0, 0)))
            # create vertex list
            self._shown[position] = self.batch.add(count, GL_QUADS, self.texturepack[self.type[position]],
                    ('v3f/static', vertex_data),
                    ('t2f/static', texture_data))

    def _show_own_block(self, position, texture):
        x, y, z = position
        # only show exposed faces
        index = 0
        count = 4
        vertex_data = cube_vertices(x, y, z, 0.5)
        texture_data = list(texture)
        for dx, dy, dz in []:#FACES:
            if (x + dx, y + dy, z + dz) in self.world:
                count -= 4
                i = index * 12
                j = index * 8
                del vertex_data[i:i + 12]
                del texture_data[j:j + 8]
            else:
                index += 1
        # create vertex list
        self._shown[position] = self.batch.add(count, GL_QUADS, self.group,
            ('v3f/static', vertex_data),
            ('t2f/static', texture_data))

    def hide_block(self, position, immediate=True):
        self.shown.pop(position)
        if immediate:
            self._hide_block(position)
        else:
            self.enqueue(self._hide_block, position)
    def _hide_block(self, position):
        self._shown.pop(position).delete()
    def show_sector(self, sector):
        for position in self.sectors.get(sector, []):
            if position not in self.shown and self.exposed(position):
                if self.type[position] == "GOLDORE":
                    self.show_own_block(position, False)
                else:
                    self.show_block(position, False)
    def hide_sector(self, sector):
        for position in self.sectors.get(sector, []):
            if position in self.shown:
                self.hide_block(position, False)
    def change_sectors(self, before, after):
        before_set = set()
        after_set = set()
        pad = 4
        for dx in xrange(-pad, pad + 1):
            for dy in [0]: # xrange(-pad, pad + 1):
                for dz in xrange(-pad, pad + 1):
                    if dx ** 2 + dy ** 2 + dz ** 2 > (pad + 1) ** 2:
                        continue
                    if before:
                        x, y, z = before
                        before_set.add((x + dx, y + dy, z + dz))
                    if after:
                        x, y, z = after
                        after_set.add((x + dx, y + dy, z + dz))
        show = after_set - before_set
        hide = before_set - after_set
        for sector in show:
            self.show_sector(sector)
        for sector in hide:
            self.hide_sector(sector)
    def enqueue(self, func, *args):
        self.queue.append((func, args))
    def dequeue(self):
        func, args = self.queue.pop(0)
        func(*args)
    def process_queue(self):
        start = time.clock()
        while self.queue and time.clock() - start < 1 / 60.0:
            self.dequeue()
    def process_entire_queue(self):
        while self.queue:
            self.dequeue()

class Window(pyglet.window.Window):
    def __init__(self, client, *args, **kwargs):
        super(Window, self).__init__(*args, **kwargs)
        self.exclusive = False
        self.flying = False
        self.strafe = [0, 0]
        self.position = (0, 16, 16)
        self.rotation = (45, -45) # first left,right - second up,down
        self.sector = None
        self.reticle = None
        self.dy = 0
        self.inventory = [BRICK, GRASS, SAND]
        self.block = self.inventory[0]
        self.num_keys = [
            key._1, key._2, key._3, key._4, key._5,
            key._6, key._7, key._8, key._9, key._0]
        self.client = client
        self.model = Model(self.client)
        self.label = pyglet.text.Label('', font_name='Arial', font_size=18, 
            x=10, y=self.height - 10, anchor_x='left', anchor_y='top', 
            color=(0, 0, 0, 255))
        pyglet.clock.schedule_interval(self.update, 1.0 / 60)
    def set_exclusive_mouse(self, exclusive):
        super(Window, self).set_exclusive_mouse(exclusive)
        self.exclusive = exclusive
    def get_sight_vector(self):
        x, y = self.rotation
        m = math.cos(math.radians(y))
        dy = math.sin(math.radians(y))
        dx = math.cos(math.radians(x - 90)) * m
        dz = math.sin(math.radians(x - 90)) * m
        return (dx, dy, dz)
    def get_motion_vector(self):
        if any(self.strafe):
            x, y = self.rotation
            strafe = math.degrees(math.atan2(*self.strafe))
            if self.flying:
                m = math.cos(math.radians(y))
                dy = math.sin(math.radians(y))
                if self.strafe[1]:
                    dy = 0.0
                    m = 1
                if self.strafe[0] > 0:
                    dy *= -1
                dx = math.cos(math.radians(x + strafe)) * m
                dz = math.sin(math.radians(x + strafe)) * m
            else:
                dy = 0.0
                dx = math.cos(math.radians(x + strafe))
                dz = math.sin(math.radians(x + strafe))
        else:
            dy = 0.0
            dx = 0.0
            dz = 0.0
        return (dx, dy, dz)
    def update(self, dt):
        self.model.process_queue()
        sector = sectorize(self.position)
        if sector != self.sector:
            self.model.change_sectors(self.sector, sector)
            if self.sector is None:
                self.model.process_entire_queue()
            self.sector = sector
        m = 8
        dt = min(dt, 0.2)
        for _ in xrange(m):
            self._update(dt / m)
    def _update(self, dt):
        # walking
        speed = 15 if self.flying else 5
        d = dt * speed
        dx, dy, dz = self.get_motion_vector()
        dx, dy, dz = dx * d, dy * d, dz * d
        # gravity
        if not self.flying:
            self.dy -= dt * 0.00044 # g force, should be = jump_speed * 0.5 / max_jump_height
            self.dy = max(self.dy, -0.5) # terminal velocity
            dy += self.dy
        # collisions
        x, y, z = self.position
        x, y, z = self.collide((x + dx, y + dy, z + dz), 2)
        self.position = (x, y, z)
    def collide(self, position, height):
        pad = 0.25
        p = list(position)
        np = normalize(position)
        for face in FACES: # check all surrounding blocks
            for i in xrange(3): # check each dimension independently
                if not face[i]:
                    continue
                d = (p[i] - np[i]) * face[i]
                if d < pad:
                    continue
                for dy in xrange(height): # check each height
                    op = list(np)
                    op[1] -= dy
                    op[i] += face[i]
                    op = tuple(op)
                    if op not in self.model.world:
                        continue
                    p[i] -= (d - pad) * face[i]
                    if face == (0, -1, 0) or face == (0, 1, 0):
                        self.dy = 0
                    break
        return tuple(p)
    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        return
        x, y, z = self.position
        dx, dy, dz = self.get_sight_vector()
        d = scroll_y * 10
        self.position = (x + dx * d, y + dy * d, z + dz * d)
    def on_mouse_press(self, x, y, button, modifiers):
        if self.exclusive:
            vector = self.get_sight_vector()
            block, previous = self.model.hit_test(self.position, vector)
            if button == pyglet.window.mouse.LEFT:
                if block:
                    texture = self.model.world[block]
                    if texture != STONE:
                        self.model.remove_block(block)
            else:
                if previous:
                    self.model.add_block(previous, self.block)
        else:
            self.set_exclusive_mouse(True)
    def on_mouse_motion(self, x, y, dx, dy):
        if self.exclusive:
            m = 0.15
            x, y = self.rotation
            x, y = x + dx * m, y + dy * m
            y = max(-90, min(90, y))
            self.rotation = (x, y)
    def on_key_press(self, symbol, modifiers):
        if symbol == key.W:
            self.strafe[0] -= 1
        elif symbol == key.S:
            self.strafe[0] += 1
        elif symbol == key.A:
            self.strafe[1] -= 1
        elif symbol == key.D:
            self.strafe[1] += 1
        elif symbol == key.SPACE:
            if self.dy == 0:
                self.dy = 0.015 # jump speed
        elif symbol == key.ESCAPE:
            self.set_exclusive_mouse(False)
        elif symbol == key.TAB:
            self.flying = not self.flying
        elif symbol in self.num_keys:
            index = (symbol - self.num_keys[0]) % len(self.inventory)
            self.block = self.inventory[index]
    def on_key_release(self, symbol, modifiers):
        if symbol == key.W:
            self.strafe[0] += 1
        elif symbol == key.S:
            self.strafe[0] -= 1
        elif symbol == key.A:
            self.strafe[1] += 1
        elif symbol == key.D:
            self.strafe[1] -= 1
    def on_resize(self, width, height):
        # label
        self.label.y = height - 10
        # reticle
        if self.reticle:
            self.reticle.delete()
        x, y = self.width // 2, self.height // 2
        n = 10
        self.reticle = pyglet.graphics.vertex_list(4,
            ('v2i', (x - n, y, x + n, y, x, y - n, x, y + n))
        )
    def set_2d(self):
        width, height = self.get_size()
        glDisable(GL_DEPTH_TEST)
        glViewport(0, 0, width, height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0, width, 0, height, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
    def set_3d(self):
        width, height = self.get_size()
        glEnable(GL_DEPTH_TEST)
        glViewport(0, 0, width, height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(65.0, width / float(height), 0.1, 60.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        x, y = self.rotation
        glRotatef(x, 0, 1, 0)
        glRotatef(-y, math.cos(math.radians(x)), 0, math.sin(math.radians(x)))
        x, y, z = self.position
        glTranslatef(-x, -y, -z)
    def on_draw(self):
        self.clear()
        self.set_3d()
        glColor3d(1, 1, 1)
        self.model.batch.draw()
        self.draw_focused_block()
        self.set_2d()
        self.draw_label()
        #self.draw_reticle()
    def draw_focused_block(self):
        vector = self.get_sight_vector()
        block = self.model.hit_test(self.position, vector)[0]
        if block:
            x, y, z = block
            vertex_data = cube_vertices(x, y, z, 0.51)
            glColor3d(0, 0, 0)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            pyglet.graphics.draw(4, GL_QUADS, ('v3f/static', vertex_data))
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
    def draw_label(self):
        x, y, z = self.position
        self.label.text = '%02d (%.2f, %.2f, %.2f) %d / %d' % (
            pyglet.clock.get_fps(), x, y, z, 
            len(self.model._shown), len(self.model.world))
        self.label.draw()
    def draw_reticle(self):
        glColor3d(0, 0, 0)
        self.reticle.draw(GL_LINES)

def setup_fog():
    glEnable(GL_FOG)
    glFogfv(GL_FOG_COLOR, (GLfloat * 4)(0.5, 0.69, 1.0, 1))
    glHint(GL_FOG_HINT, GL_DONT_CARE)
    glFogi(GL_FOG_MODE, GL_LINEAR)
    glFogf(GL_FOG_DENSITY, 0.35)
    glFogf(GL_FOG_START, 20.0)
    glFogf(GL_FOG_END, 60.0)

def setup():
    glClearColor(0.5, 0.69, 1.0, 1)
    glEnable(GL_CULL_FACE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
    setup_fog()

def commence_vis(client):
    global window
    window = Window(client, width=800, height=600, caption='Pyglet', resizable=True, visible=False)
    #window.set_exclusive_mouse(True)
    setup()
    for i in range(0,50):
        step_vis()

def step_vis():
    pyglet.clock.tick()
    pyglet.image.get_buffer_manager().get_color_buffer().save('./micropsi_server/static/minecraft/screenshot_write.jpg')
    move('./micropsi_server/static/minecraft/screenshot_write.jpg', './micropsi_server/static/minecraft/screenshot.jpg')
    global window
    window.switch_to()
    window.model.reload()
    window.dispatch_events()
    window.dispatch_event('on_draw')
    window.flip()