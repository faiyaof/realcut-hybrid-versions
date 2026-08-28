      
local isEditor = (Amaz.Macros and Amaz.Macros.EditorSDK) and true or false
local exports = exports or {}
local AETransform = AETransform or {}
AETransform.__index = AETransform
---@class AETransform : ScriptComponent
---@field active_cam_fovx number
---@field compositeSize Vector2f
---@field layerSize Vector2f
---@field is3DLayer boolean
---@field anchorPoint Vector3f
---@field orientation Vector3f
---@field position Vector3f
---@field scale Vector3f
---@field xRotation number [UI(Range={-360, 360}, Drag)]
---@field yRotation number [UI(Range={-360, 360}, Drag)]
---@field rotation number [UI(Range={-360, 360}, Drag)]
---@field opacity number [UI(Range={0, 100}, Drag)]
---@field mirrorEdge boolean
---@field InputTex Texture
---@field OutputTex Texture

function AETransform.new(construct, ...)
    local self = setmetatable({}, AETransform)

    self.active_cam_fovx = 39.6
    self.compositeSize = Amaz.Vector2f(1080, 1080)
    self.layerSize = Amaz.Vector2f(1080, 1080)

    self.is3DLayer = true
    self.anchorPoint = Amaz.Vector3f(0, 0, 0)
    self.position = Amaz.Vector3f(0, 0, 0)
    self.scale = Amaz.Vector3f(100, 100, 100)
    self.orientation = Amaz.Vector3f(0, 0, 0)
    self.rotation = 0
    self.xRotation = 0
    self.yRotation = 0
    self.opacity = 100

    self.p0_anchorPoint = Amaz.Vector3f(0, 0, 0)
    self.p0_position = Amaz.Vector3f(0, 0, 0)
    self.p0_scale = Amaz.Vector3f(100, 100, 100)
    self.p0_orientation = Amaz.Vector3f(0, 0, 0)
    self.p0_rotation = 0
    self.p0_xRotation = 0
    self.p0_yRotation = 0

    self.p1_anchorPoint = Amaz.Vector3f(0, 0, 0)
    self.p1_position = Amaz.Vector3f(0, 0, 0)
    self.p1_scale = Amaz.Vector3f(100, 100, 100)
    self.p1_orientation = Amaz.Vector3f(0, 0, 0)
    self.p1_rotation = 0
    self.p1_xRotation = 0
    self.p1_yRotation = 0

    self.expandRight = 0.0
    self.expandLeft = 0.0
    self.expandUp = 0.0
    self.expandDown = 0.0
    self.mirrorEdge = false
    self.InputTex = nil
    self.OutputTex = nil


    if construct and AETransform.constructor then AETransform.constructor(self, ...) end
    return self
end

function AETransform:constructor()

end

function AETransform:paramListener(_param, _func)
    if self[_param] ~= nil then
        if self["last_".._param] == nil or self["last_".._param] ~= self[_param] then
            _func()
            self["last_".._param] = self[_param]
        end
    end
end

function AETransform:onStart(comp)
    self.entity = comp.entity
    self.ae_cam = self.entity:searchEntity("cam_ae_transform"):getComponent("Camera")
    self.expand_tile_trans = self.entity:searchEntity("expand_tile"):getComponent("Transform")
    self.father_trans = self.entity:searchEntity("father_trans"):getComponent("Transform")
    self.child_trans = self.entity:searchEntity("child_trans"):getComponent("Transform")
    self.p0_father_trans = self.entity:searchEntity("p0_father_trans"):getComponent("Transform")
    self.p0_child_trans = self.entity:searchEntity("p0_child_trans"):getComponent("Transform")
    self.p1_father_trans = self.entity:searchEntity("p1_father_trans"):getComponent("Transform")
    self.p1_child_trans = self.entity:searchEntity("p1_child_trans"):getComponent("Transform")

    self.child_mat = self.entity:searchEntity("expand_tile"):getComponent("MeshRenderer").material
end


function AETransform:setEffectAttr(key, value, comp)
    local function _setEffectAttr(_key, _value)
        if self[_key] ~= nil then
            self[_key] = _value
            if comp and comp.properties ~= nil then
                comp.properties:set(_key, _value)
            end
        end
    end

    local function setParamVectorNf(paramKey, channel, paramValue)
        local pamam =self[paramKey]
        if pamam then
            pamam[channel] = paramValue
            _setEffectAttr(paramKey, pamam)
        end
    end

    local vectorNf_params = {
        composite_size_x = {"compositeSize", "x"}, composite_size_y = {"compositeSize", "y"},
        layer_size_x = {"layerSize", "x"}, layer_size_y = {"layerSize", "y"},
        pivot_x = {"anchorPoint", "x"}, pivot_y = {"anchorPoint", "y"}, pivot_z = {"anchorPoint", "z"},
        xPosition = {"position", "x"}, yPosition = {"position", "y"}, zPosition = {"position", "z"},
        position_x = {"position", "x"}, position_y = {"position", "y"}, position_z = {"position", "z"},
        scale_x = {"scale", "x"}, scale_y = {"scale", "y"}, scale_z = {"scale", "z"},
        direction_x = {"orientation", "x"}, direction_y = {"orientation", "y"}, direction_z = {"orientation", "z"},
        p0_pivot_x = {"p0_anchorPoint", "x"}, p0_pivot_y = {"p0_anchorPoint", "y"}, p0_pivot_z = {"p0_anchorPoint", "z"},
        p0_xPosition = {"p0_position", "x"}, p0_yPosition = {"p0_position", "y"}, p0_zPosition = {"p0_position", "z"},
        p0_position_x = {"p0_position", "x"}, p0_position_y = {"p0_position", "y"}, p0_position_z = {"p0_position", "z"},
        p0_scale_x = {"p0_scale", "x"}, p0_scale_y = {"p0_scale", "y"}, p0_scale_z = {"p0_scale", "z"},
        p0_direction_x = {"p0_orientation", "x"}, p0_direction_y = {"p0_orientation", "y"}, p0_direction_z = {"p0_orientation", "z"},
        p1_pivot_x = {"p1_anchorPoint", "x"}, p1_pivot_y = {"p1_anchorPoint", "y"}, p1_pivot_z = {"p1_anchorPoint", "z"},
        p1_xPosition = {"p1_position", "x"}, p1_yPosition = {"p1_position", "y"}, p1_zPosition = {"p1_position", "z"},
        p1_position_x = {"p1_position", "x"}, p1_position_y = {"p1_position", "y"}, p1_position_z = {"p1_position", "z"},
        p1_scale_x = {"p1_scale", "x"}, p1_scale_y = {"p1_scale", "y"}, p1_scale_z = {"p1_scale", "z"},
        p1_direction_x = {"p1_orientation", "x"}, p1_direction_y = {"p1_orientation", "y"}, p1_direction_z = {"p1_orientation", "z"},
    }
    if vectorNf_params[key] then
        local paramKey = vectorNf_params[key][1]
        local channel = vectorNf_params[key][2]
        setParamVectorNf(paramKey, channel, value)
    elseif key == "position"
        or key == "anchorPoint"
        or key == "scale"
        or key == "orientation"
    then
        if value.z ~= nil then
            _setEffectAttr(key, value)
        else
            -- Vector2f to Vector3f
            _setEffectAttr(key, Amaz.Vector3f(value.x, value.y, 0))
        end
    else
        _setEffectAttr(key, value)
    end
end


function AETransform:_rotateByAEAxis(_trans, _direction, _euler_angle)
    -- ae xyz, editor yxz
    local up = Amaz.Vector3f(0.0, 1.0, 0.0)      
    local right = Amaz.Vector3f(1.0, 0.0, 0.0)   
    local forward = Amaz.Vector3f(0.0, 0.0, 1.0) 

    local cur_orientation = Amaz.Quaternionf.axisAngleToQuaternion(right,   _direction.x/180*math.pi) *
                            Amaz.Quaternionf.axisAngleToQuaternion(up,      -_direction.y/180*math.pi) * 
                            Amaz.Quaternionf.axisAngleToQuaternion(forward, -_direction.z/180*math.pi)

    up      = Amaz.Quaternionf.rotateVectorByQuat(cur_orientation, up)
    right   = Amaz.Quaternionf.rotateVectorByQuat(cur_orientation, right)
    forward = Amaz.Quaternionf.rotateVectorByQuat(cur_orientation, forward)

    cur_orientation = Amaz.Quaternionf.axisAngleToQuaternion(right,   _euler_angle.x/180*math.pi) * 
                    Amaz.Quaternionf.axisAngleToQuaternion(up,      -_euler_angle.y/180*math.pi) * 
                    Amaz.Quaternionf.axisAngleToQuaternion(forward, -_euler_angle.z/180*math.pi) * 
                    cur_orientation
    
    _trans.localOrientation = cur_orientation
end


function AETransform:onUpdate(comp, deltaTime)
    self.width = Amaz.BuiltinObject.getInputTextureWidth()
    self.height = Amaz.BuiltinObject.getInputTextureHeight()
    if self.OutputTex then
        self.width = self.OutputTex.width
        self.height = self.OutputTex.height
    end
    local ratio = self.width/self.height

    self.expand_tile_trans.localScale = Amaz.Vector3f(1.0+self.expandRight+self.expandLeft, 1.0+self.expandUp+self.expandDown, 1.0)
    self.expand_tile_trans.localPosition = Amaz.Vector3f(
        self.expandRight-self.expandLeft,
        self.expandUp-self.expandDown,
        0.0
    )

    if self.is3DLayer then
        self.ae_cam.type = 0
        local pos_z0 = ratio/math.tan(self.active_cam_fovx*0.5/180*math.pi)
        self.ae_cam.fovy = math.atan(1/pos_z0)/math.pi*180*2

        local rotate = Amaz.Vector3f(self.xRotation, self.yRotation, self.rotation)
        self:_rotateByAEAxis(self.father_trans, self.orientation, rotate)
        self.father_trans.localPosition = Amaz.Vector3f(
            (self.position.x / self.compositeSize.x - 0.5) * 2 * ratio,
            (1.0-self.position.y / self.compositeSize.y - 0.5) * 2,
            -self.position.z*2/self.compositeSize.y
        )
        self.child_trans.localPosition = Amaz.Vector3f(
            -(self.anchorPoint.x / self.layerSize.x - 0.5) * 2 * ratio, 
            -(1.0-self.anchorPoint.y / self.layerSize.y - 0.5) * 2, 
            self.anchorPoint.z * 2 / self.layerSize.y
        )
        self.child_trans.localEulerAngle = Amaz.Vector3f(0,0,0)
        -- parent 0
        local rotate = Amaz.Vector3f(self.p0_xRotation, self.p0_yRotation, self.p0_rotation)
        self:_rotateByAEAxis(self.p0_father_trans, self.p0_orientation, rotate)
        self.p0_father_trans.localPosition = Amaz.Vector3f(
            (self.p0_position.x / self.compositeSize.x - 0.5) * 2 * ratio,
            (1.0-self.p0_position.y / self.compositeSize.y - 0.5) * 2,
            -self.p0_position.z*2/self.compositeSize.y
        )

        self.p0_child_trans.localPosition = Amaz.Vector3f(
            -(self.p0_anchorPoint.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            -(1.0-self.p0_anchorPoint.y / self.compositeSize.y - 0.5) * 2, 
            self.p0_anchorPoint.z * 2 / self.compositeSize.y
        )
        self.p0_child_trans.localEulerAngle = Amaz.Vector3f(0,0,0)
        -- parent 1
        local rotate = Amaz.Vector3f(self.p1_xRotation, self.p1_yRotation, self.p1_rotation)
        self:_rotateByAEAxis(self.p1_father_trans, self.p1_orientation, rotate)
        self.p1_father_trans.localPosition = Amaz.Vector3f(
            (self.p1_position.x / self.compositeSize.x - 0.5) * 2 * ratio,
            (1.0-self.p1_position.y / self.compositeSize.y - 0.5) * 2,
            -pos_z0-self.p1_position.z*2/self.compositeSize.y
        )

        self.p1_child_trans.localPosition = Amaz.Vector3f(
            -(self.p1_anchorPoint.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            -(1.0-self.p1_anchorPoint.y / self.compositeSize.y - 0.5) * 2, 
            self.p1_anchorPoint.z * 2 / self.compositeSize.y
        )
        self.p1_child_trans.localEulerAngle = Amaz.Vector3f(0,0,0)
    else
        self.ae_cam.type = 1

        self.father_trans.localEulerAngle = Amaz.Vector3f(0,0,0)
        self.father_trans.localPosition = Amaz.Vector3f(
            (self.position.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            (1.0-self.position.y / self.compositeSize.y - 0.5) * 2, 
            -10
        )
        self.child_trans.localPosition = Amaz.Vector3f(
            -(self.anchorPoint.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            -(1.0-self.anchorPoint.y / self.compositeSize.y - 0.5) * 2, 
            0
        )
        self.child_trans.localEulerAngle = Amaz.Vector3f(0, 0, -self.rotation)
        -- parent 0
        self.p0_father_trans.localEulerAngle = Amaz.Vector3f(0,0,0)
        self.p0_father_trans.localPosition = Amaz.Vector3f(
            (self.p0_position.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            (1.0-self.p0_position.y / self.compositeSize.y - 0.5) * 2, 
            -10
        )
        self.p0_child_trans.localPosition = Amaz.Vector3f(
            -(self.p0_anchorPoint.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            -(1.0-self.p0_anchorPoint.y / self.compositeSize.y - 0.5) * 2, 
            0
        )
        self.p0_child_trans.localEulerAngle = Amaz.Vector3f(0, 0, -self.p0_rotation)
        -- parent 1
        self.p1_father_trans.localEulerAngle = Amaz.Vector3f(0,0,0)
        self.p1_father_trans.localPosition = Amaz.Vector3f(
            (self.p1_position.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            (1.0-self.p1_position.y / self.compositeSize.y - 0.5) * 2, 
            -10
        )
        self.p1_child_trans.localPosition = Amaz.Vector3f(
            -(self.p1_anchorPoint.x / self.compositeSize.x - 0.5) * 2 * ratio, 
            -(1.0-self.p1_anchorPoint.y / self.compositeSize.y - 0.5) * 2, 
            0
        )
        self.p1_child_trans.localEulerAngle = Amaz.Vector3f(0, 0, -self.p1_rotation)
    end
    self.father_trans.localScale = Amaz.Vector3f(self.scale.x/100.0*(self.layerSize.x/self.compositeSize.x), self.scale.y/100.0*(self.layerSize.y/self.compositeSize.y), self.scale.z/100.0)
    self.child_trans.localScale = Amaz.Vector3f(ratio, 1, 1)
    self.p0_father_trans.localScale = self.p0_scale / 100.0
    self.p1_father_trans.localScale = self.p1_scale / 100.0

    self.child_mat:setFloat("alpha", self.opacity / 100.0)
    self.child_mat:setFloat("mirrorEdge", self.mirrorEdge and 1 or 0)

    self.child_mat:setTex("inputTex", self.InputTex)
    self.ae_cam.renderTexture = self.OutputTex
end

exports.AETransform = AETransform
return exports
