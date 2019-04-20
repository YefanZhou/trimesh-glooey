import glooey
import numpy as np
import pyglet
from pyrender.trackball import Trackball
import trimesh
import trimesh.transformations as tf

from pyglet.gl import *  # NOQA


class SceneGroup(pyglet.graphics.Group):

    def __init__(
        self,
        rect,
        camera_fovy=60,
        camera_transform=None,
        view_transform=None,
        parent=None,
    ):
        super().__init__(parent)
        self.rect = rect

        self.camera_fovy = camera_fovy

        # transform from world coords to camera coords
        if camera_transform is None:
            camera_transform = np.eye(4)
        self.camera_transform = camera_transform

        # transform from world coords to view coords
        if view_transform is None:
            view_transform = np.eye(4)
        self.view_transform = view_transform

    def set_state(self):
        glPushAttrib(GL_ENABLE_BIT)
        glEnable(GL_SCISSOR_TEST)
        glScissor(
            int(self.rect.left),
            int(self.rect.bottom),
            int(self.rect.width),
            int(self.rect.height),
        )

        self._mode = (GLint)()
        glGetIntegerv(GL_MATRIX_MODE, self._mode)
        self._viewport = (GLint * 4)()
        glGetIntegerv(GL_VIEWPORT, self._viewport)

        left, bottom = int(self.rect.left), int(self.rect.bottom)
        width, height = int(self.rect.width), int(self.rect.height)
        glViewport(left, bottom, width, height)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        gluPerspective(self.camera_fovy, width / height, 0.01, 1000.0)
        glMatrixMode(GL_MODELVIEW)

        glClearColor(*[.99, .99, .99, 1.0])

        self._enable_depth()
        self._enable_color_material()
        self._enable_blending()
        self._enable_smooth_lines()
        self._enable_lighting()
        self._clear_buffers()

        glPushMatrix()
        glLoadIdentity()
        glMultMatrixf(trimesh.rendering.matrix_to_gl(self.camera_transform))
        glMultMatrixf(trimesh.rendering.matrix_to_gl(self.view_transform))

    def unset_state(self):
        glPopMatrix()

        glClearColor(*[0, 0, 0, 0])

        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(self._mode.value)
        glViewport(
            self._viewport[0],
            self._viewport[1],
            self._viewport[2],
            self._viewport[3],
        )

        glPopAttrib()

    def _enable_depth(self):
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)

        glDepthRange(0.0, 100.0)
        glDepthFunc(GL_LEQUAL)
        glClearDepth(1.0)

    def _enable_color_material(self):
        glEnable(GL_COLOR_MATERIAL)

        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glShadeModel(GL_SMOOTH)

        v = trimesh.rendering.vector_to_gl
        glMaterialfv(GL_FRONT, GL_AMBIENT, v(0.192250, 0.192250, 0.192250))
        glMaterialfv(GL_FRONT, GL_DIFFUSE, v(0.507540, 0.507540, 0.507540))
        glMaterialfv(GL_FRONT, GL_SPECULAR, v(0.5082730, .5082730, .5082730))
        glMaterialf(GL_FRONT, GL_SHININESS, 0.4 * 128.0)

    def _enable_blending(self):
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def _enable_smooth_lines(self):
        # Make things generally less ugly.
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)
        glLineWidth(1.5)
        glPointSize(4)

    def _enable_lighting(self):
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)

        v = trimesh.rendering.vector_to_gl
        glLightfv(GL_LIGHT0, GL_AMBIENT, v(0.5, 0.5, 0.5, 1.0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, v(1.0, 1.0, 1.0, 1.0))
        glLightfv(GL_LIGHT0, GL_SPECULAR, v(1.0, 1.0, 1.0, 1.0))
        glLightfv(GL_LIGHT0, GL_POSITION, v(0.0, 0.0, 0.0, 1.0))

    def _clear_buffers(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)


class MeshGroup(pyglet.graphics.Group):

    def __init__(self, transform=None, texture=None, parent=None):
        super().__init__(parent)
        if transform is None:
            transform = np.eye(4)
        self.transform = transform
        self.texture = texture

    def set_state(self):
        glPushMatrix()
        glMultMatrixf(trimesh.rendering.matrix_to_gl(self.transform))

        if self.texture:
            glEnable(self.texture.target)
            glBindTexture(self.texture.target, self.texture.id)

    def unset_state(self):
        if self.texture:
            glDisable(self.texture.target)

        glPopMatrix()


class SceneWidget(glooey.Widget):

    def __init__(self, scene):
        super().__init__()
        self.scene = scene
        self.scene_group = None
        self.vertex_list = {}  # key: geometry_name, value: vertex_list
        self.textures = {}     # key: geometry_name, value: vertex_list
        self.__trackball = None

    @property
    def _trackball(self):
        if self.__trackball is None:
            self.__trackball = Trackball(
                np.eye(4),
                (self.rect.width, self.rect.height),
                self.scene.scale,
                self.scene.centroid,
            )
        return self.__trackball

    def do_claim(self):
        return 0, 0

    def do_regroup(self):
        if not self.vertex_list:
            return

        self.scene_group = SceneGroup(
            rect=self.rect,
            camera_fovy=self.scene.camera.fov[1],
            camera_transform=np.linalg.inv(self.scene.camera.transform),
            view_transform=self._trackball.pose.copy(),
            parent=self.group,
        )
        for geometry_name, vertex_list in self.vertex_list.items():
            mesh_group = MeshGroup(
                transform=transform,
                texture=self.textures.get(geometry_name),
                parent=self.scene_group,
            )
            self.batch.migrate(
                vertex_list,
                GL_TRIANGLES,
                mesh_group,
                self.batch,
            )

    def do_draw(self):
        # Because the vertex list can't change, we don't need to do anything if
        # the vertex list is already set.
        if self.vertex_list:
            return

        self.scene_group = SceneGroup(
            rect=self.rect,
            camera_fovy=self.scene.camera.fov[1],
            camera_transform=np.linalg.inv(self.scene.camera.transform),
            view_transform=self._trackball.pose.copy(),
            parent=self.group,
        )

        node_names = self.scene.graph.nodes_geometry
        for node_name in node_names:
            transform, geometry_name = self.scene.graph[node_name]
            geometry = self.scene.geometry[geometry_name]
            assert isinstance(geometry, trimesh.Trimesh)

            if hasattr(geometry, 'visual') and \
                    hasattr(geometry.visual, 'material'):
                self.textures[geometry_name] = \
                    trimesh.rendering.material_to_texture(
                        geometry.visual.material)

            mesh_group = MeshGroup(
                transform=transform,
                texture=self.textures.get(geometry_name),
                parent=self.scene_group,
            )
            args = trimesh.rendering.mesh_to_vertexlist(
                geometry, group=mesh_group
            )
            self.vertex_list[geometry_name] = self.batch.add_indexed(*args)

    def do_undraw(self):
        if not self.vertex_list:
            return
        for vertex_list in self.vertex_list.values():
            vertex_list.delete()
        self.vertex_list = {}
        self.textures = {}

    def on_mouse_press(self, x, y, buttons, modifiers):
        self._trackball.set_state(Trackball.STATE_ROTATE)
        if (buttons == pyglet.window.mouse.LEFT):
            ctrl = (modifiers & pyglet.window.key.MOD_CTRL)
            shift = (modifiers & pyglet.window.key.MOD_SHIFT)
            if (ctrl and shift):
                self._trackball.set_state(Trackball.STATE_ZOOM)
            elif ctrl:
                self._trackball.set_state(Trackball.STATE_ROLL)
            elif shift:
                self._trackball.set_state(Trackball.STATE_PAN)
        elif (buttons == pyglet.window.mouse.MIDDLE):
            self._trackball.set_state(Trackball.STATE_PAN)
        elif (buttons == pyglet.window.mouse.RIGHT):
            self._trackball.set_state(Trackball.STATE_ZOOM)

        self._trackball.down(np.array([x, y]))
        if self.scene_group:
            self.scene_group.view_transform = self._trackball.pose.copy()
        self._draw()

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        # detect crossing edge between widgets
        x_prev = x - dx
        y_prev = y - dy
        left, bottom = self.rect.left, self.rect.bottom
        width, height = self.rect.width, self.rect.height
        if not (left <= x_prev <= left + width) or \
                not (bottom <= y_prev <= bottom + height):
            self._trackball.down(np.array([x, y]))

        self._trackball.drag(np.array([x, y]))
        if self.scene_group:
            self.scene_group.view_transform = self._trackball.pose.copy()
        self._draw()

    def on_mouse_scroll(self, x, y, dx, dy):
        self._trackball.scroll(dy)
        if self.scene_group:
            self.scene_group.view_transform = self._trackball.pose.copy()
        self._draw()


# -----------------------------------------------------------------------------


def create_scene1():
    scene = trimesh.Scene()
    for _ in range(20):
        geom = trimesh.creation.axis(0.02)
        R = tf.random_rotation_matrix()
        T = tf.translation_matrix(np.random.uniform(-1, 1, (3,)))
        scene.add_geometry(geom, transform=T @ R)
    return scene


def create_scene2():
    scene = trimesh.Scene()
    for _ in range(5):
        geom = trimesh.load('models/fuze.obj')
        R = tf.random_rotation_matrix()
        T = tf.translation_matrix(np.random.uniform(-0.3, 0.3, (3,)))
        scene.add_geometry(geom, transform=T @ R)
    return scene


def main():
    np.random.seed(0)

    window = pyglet.window.Window(width=1295, height=975)
    gui = glooey.Gui(window)

    grid = glooey.Grid(2, 2)
    grid.set_padding(5)

    scene = create_scene1()
    widget = SceneWidget(scene)
    grid[0, 0] = widget
    scene = create_scene2()
    widget = SceneWidget(scene)
    grid[0, 1] = widget

    image = pyglet.image.load('images/beach.jpg')
    widget = glooey.Image(image)
    grid[1, 0] = widget

    hbox = glooey.HBox()
    widget = glooey.Button(text='yes')
    widget.push_handlers(on_click=lambda w: print(f'[{w.text}] clicked!'))
    hbox.add(widget)
    widget = glooey.Button(text='no')
    widget.push_handlers(on_click=lambda w: print(f'[{w.text}] clicked!'))
    hbox.add(widget)
    grid[1, 1] = hbox

    gui.add(grid)

    pyglet.app.run()


if __name__ == '__main__':
    main()
